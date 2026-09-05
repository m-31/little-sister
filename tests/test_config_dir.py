"""The configuration directory: roots, aspect forms, and the startup contract
(ADR-0031)."""
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import TestCase

from little_sister import self_report
from little_sister.config_dir import (
    ASPECTS,
    CONFIG_DIR_ENV,
    announce_aspects,
    aspect_files,
    aspect_in,
    config_roots,
    forget_aspects,
    register_aspect,
    registered_aspects,
    sole_aspect_file,
)
from little_sister.errors import ConfigError
from little_sister.reasons import slug


@contextmanager
def _cwd(directory):
    """Run inside ``directory``, restoring the previous working directory. The
    default root (``config``) is relative, so the tests that exercise it have to
    stand somewhere known."""
    previous = os.getcwd()
    os.chdir(directory)
    try:
        yield Path(directory)
    finally:
        os.chdir(previous)


@contextmanager
def _no_config_dir_env():
    """With ``LITTLE_SISTER_CONFIG_DIR`` unset — conftest pins it for the rest of
    the suite, and the default-path rules cannot be seen through it."""
    previous = os.environ.pop(CONFIG_DIR_ENV, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[CONFIG_DIR_ENV] = previous


class RootTests(TestCase):
    def test_default_root_is_config_in_the_working_directory(self):
        with tempfile.TemporaryDirectory() as directory, _cwd(directory) as here:
            (here / "config").mkdir()
            with _no_config_dir_env():
                self.assertEqual([root.resolve() for root in config_roots()],
                                 [(here / "config").resolve()])

    def test_no_config_directory_is_fatal(self):
        with tempfile.TemporaryDirectory() as directory, _cwd(directory):
            with _no_config_dir_env(), self.assertRaises(ConfigError) as caught:
                config_roots()
            self.assertIn("config", str(caught.exception))
            self.assertIn(CONFIG_DIR_ENV, str(caught.exception))

    def test_legacy_layout_is_named_in_the_refusal(self):
        # Detecting the old layout is a diagnostic, not compatibility: an
        # unmigrated deployment must be told which files to move, not served a
        # page about nothing (ADR-0031 §7).
        with tempfile.TemporaryDirectory() as directory, _cwd(directory) as here:
            (here / "checks").mkdir()
            (here / "config.yaml").write_text("timezone: UTC\n")
            (here / "users.yaml").write_text("admin: {password: a}\n")
            with _no_config_dir_env(), self.assertRaises(ConfigError) as caught:
                config_roots()
            message = str(caught.exception)
            self.assertIn("checks/ -> config/checks/", message)
            self.assertIn("config.yaml -> config/settings.yaml", message)
            self.assertIn("users.yaml -> config/users.yaml", message)

    def test_the_retired_checks_dir_variable_is_never_read(self):
        # The break is clean: LITTLE_SISTER_CHECKS_DIR is not consulted, not even
        # as a legacy marker (ADR-0031 §7). Set to nonsense beside a healthy tree
        # it changes nothing — no redirection, no refusal, no warning.
        with tempfile.TemporaryDirectory() as directory, _cwd(directory) as here:
            (here / "config").mkdir()
            previous = os.environ.get("LITTLE_SISTER_CHECKS_DIR")
            os.environ["LITTLE_SISTER_CHECKS_DIR"] = "/nowhere/at/all"
            try:
                with _no_config_dir_env(), self.assertNoLogs(level="WARNING"):
                    roots = config_roots()
                self.assertEqual([root.resolve() for root in roots],
                                 [(here / "config").resolve()])
            finally:
                if previous is None:
                    del os.environ["LITTLE_SISTER_CHECKS_DIR"]
                else:
                    os.environ["LITTLE_SISTER_CHECKS_DIR"] = previous

    def test_the_retired_variable_alone_does_not_make_a_refusal(self):
        # …and with no config directory it is not a marker either: the refusal
        # names only the files it actually found.
        with tempfile.TemporaryDirectory() as directory, _cwd(directory):
            previous = os.environ.get("LITTLE_SISTER_CHECKS_DIR")
            os.environ["LITTLE_SISTER_CHECKS_DIR"] = "checks"
            try:
                with _no_config_dir_env(), self.assertRaises(ConfigError) as caught:
                    config_roots()
            finally:
                if previous is None:
                    del os.environ["LITTLE_SISTER_CHECKS_DIR"]
                else:
                    os.environ["LITTLE_SISTER_CHECKS_DIR"] = previous
            message = str(caught.exception)
            self.assertNotIn("LITTLE_SISTER_CHECKS_DIR", message)
            self.assertNotIn("The layout moved", message)

    def test_a_refusal_reaches_the_log_not_only_the_exception(self):
        # ADR-0031 §7: each case names the resolved path "in the exception and in
        # the log". Nothing catches a ConfigError, so an operator would otherwise
        # have only the WSGI server's traceback.
        missing = Path(tempfile.gettempdir()) / "little-sister-no-such-root"
        with self.assertLogs(level="ERROR") as logs:
            with self.assertRaises(ConfigError):
                config_roots(str(missing))
        self.assertTrue(any(str(missing.resolve()) in line
                            for line in logs.output))

    def test_named_root_that_does_not_exist_is_fatal(self):
        missing = Path(tempfile.gettempdir()) / "little-sister-no-such-root"
        with self.assertRaises(ConfigError) as caught:
            config_roots(str(missing))
        self.assertIn(str(missing.resolve()), str(caught.exception))

    def test_path_list_keeps_its_order_and_drops_blanks(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            sep = os.pathsep
            roots = config_roots(f" {d1}{sep}{sep}{d2}{sep}")
            self.assertEqual([str(root) for root in roots], [d1, d2])


class AspectFormTests(TestCase):
    def test_checks_must_be_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "checks.yaml").write_text("type: http\n")
            with self.assertRaises(ConfigError) as caught:
                aspect_in(root, "checks")
            self.assertIn("directory", str(caught.exception))

    def test_settings_must_be_a_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings").mkdir()
            with self.assertRaises(ConfigError) as caught:
                aspect_in(root, "settings")
            self.assertIn("settings.yaml", str(caught.exception))

    def test_users_accepts_the_file_and_directory_forms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users.yaml").write_text("admin: {password: a}\n")
            self.assertEqual(aspect_in(root, "users"), root / "users.yaml")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users").mkdir()
            self.assertEqual(aspect_in(root, "users"), root / "users")

    def test_users_cannot_take_both_forms_at_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users").mkdir()
            (root / "users.yaml").write_text("admin: {password: a}\n")
            with self.assertRaises(ConfigError):
                aspect_in(root, "users")

    def test_both_yaml_suffixes_is_an_error_not_a_precedence_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.yaml").write_text("/a: {title: one}\n")
            (root / "nodes.yml").write_text("/a: {title: two}\n")
            with self.assertRaises(ConfigError) as caught:
                aspect_in(root, "nodes")
            self.assertIn("more than once", str(caught.exception))

    def test_yml_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.yml").write_text("/a: {title: one}\n")
            self.assertEqual(aspect_in(root, "nodes"), root / "nodes.yml")

    def test_absent_aspect_is_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(aspect_in(Path(directory), "nodes"))


class CandidateTests(TestCase):
    """What the report on unclaimed configuration files says, and when (ADR-0070)."""

    def test_a_stray_file_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "brand.yaml").write_text("name: acme\n")
            with self.assertLogs(level="WARNING") as logs:
                announce_aspects(str(root))
            self.assertTrue(any("brand.yaml" in line for line in logs.output))

    def test_non_candidates_pass_in_silence(self):
        # The library itself ships config/checks/README.md into this tree; a
        # standing warning about a deployment's own documentation would train
        # everyone to ignore the log.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# our config\n")
            (root / "settings.yaml.bak").write_text("timezone: UTC\n")
            (root / ".keep").write_text("")
            (root / "checks").mkdir()
            with self.assertNoLogs(level="WARNING"):
                announce_aspects(str(root))

    def test_resolving_a_root_says_nothing_at_all(self):
        # The scan does not ride the resolution any more, and this is the whole of
        # why: the first resolution in a real process is somebody's registration
        # reading the aspect it has just declared.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "brand.yaml").write_text("name: acme\n")
            with self.assertNoLogs(level="WARNING"):
                config_roots(str(root))
                aspect_files("nodes", str(root))

    def test_an_aspect_registered_after_another_has_read_a_root_is_not_reported(self):
        # The defect this moved for, in the shape that produced it: every registrar
        # in this family declares its aspect and then immediately reads it, so the
        # first one to run performed the scan and named every aspect registered after
        # it as unknown for the life of the process. The whole sequence is inside the
        # assertion, because the old complaint was emitted by the *read* — asserting
        # only about the report would pass on the broken code.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "jira.yaml").write_text("project_id: '1'\n")
            (root / "identity.yaml").write_text("issuer: https://sso.example\n")
            with self.assertNoLogs(level="WARNING"):
                register_aspect("jira")
                aspect_files("jira", str(root))    # the declare-then-read shape
                register_aspect("identity")
                aspect_files("identity", str(root))
                announce_aspects(str(root))

    def test_the_report_covers_every_root_of_the_path_list(self):
        # Including a root something has already resolved: the report is not a
        # once-per-root event that an earlier read can spend.
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {title: base}\n")
            (Path(d2) / "node.yaml").write_text("/b: {title: site}\n")
            spec = f"{d1}{os.pathsep}{d2}"
            aspect_files("nodes", spec)
            with self.assertLogs(level="WARNING") as logs:
                announce_aspects(spec)
            self.assertTrue(any(str(Path(d2) / "node.yaml") in line
                                for line in logs.output))

    def test_the_message_names_who_reads_each_known_aspect(self):
        # Most of the value of reporting late: `identiy.yaml` sits one character from
        # an `identity` the line now attributes, so the log points at the typo rather
        # than merely reporting that something is unclaimed.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "identiy.yaml").write_text("issuer: https://sso.example\n")
            register_aspect("identity")
            with self.assertLogs(level="WARNING") as logs:
                announce_aspects(str(root))
            line = "\n".join(logs.output)
            self.assertIn("identity (tests)", line)
            self.assertIn("known: actions, checks", line)   # a built-in stays bare


class LayerTests(TestCase):
    def test_aspect_files_are_returned_in_path_list_order(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "nodes.yaml").write_text("/a: {title: base}\n")
            (Path(d2) / "nodes.yaml").write_text("/b: {title: site}\n")
            self.assertEqual(aspect_files("nodes", f"{d1}{os.pathsep}{d2}"),
                             [Path(d1) / "nodes.yaml", Path(d2) / "nodes.yaml"])

    def test_a_root_without_the_aspect_is_simply_absent(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d2) / "nodes.yaml").write_text("/b: {title: site}\n")
            self.assertEqual(aspect_files("nodes", f"{d1}{os.pathsep}{d2}"),
                             [Path(d2) / "nodes.yaml"])

    def test_users_first_root_wins_whole_and_warns(self):
        # Merging identities across layers is a security question wearing a
        # convenience costume — so the loser is named rather than blended.
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "users.yaml").write_text("admin: {password: a}\n")
            (Path(d2) / "users.yaml").write_text("other: {password: b}\n")
            with self.assertLogs(level="WARNING") as logs:
                winner = sole_aspect_file("users", f"{d1}{os.pathsep}{d2}")
            self.assertEqual(winner, Path(d1) / "users.yaml")
            self.assertTrue(any(str(Path(d2) / "users.yaml") in line
                                for line in logs.output))
            # and the node says so, for the life of the process (backlog #70)
            noted = [line for line in self_report.startup.lines()
                     if line.slug == slug("aspect", "users", "roots")]
            self.assertEqual(len(noted), 1)
            self.assertIn("the first wins whole", noted[0].text)

    def test_users_in_one_root_is_quiet(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "users.yaml").write_text("admin: {password: a}\n")
            self.assertEqual(sole_aspect_file("users", directory),
                             Path(directory) / "users.yaml")


if __name__ == "__main__":
    unittest.main()


class RegisteredAspectTests(TestCase):
    """A dependent package declares an aspect of its own (ADR-0035)."""

    def test_a_registered_aspect_stops_being_an_unknown_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "jira.yaml").write_text("project_id: '1'\n")
            register_aspect("jira")
            with self.assertNoLogs(level="WARNING"):
                announce_aspects(str(root))

    def test_a_registered_aspect_is_read_like_any_other(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            (Path(d1) / "jira.yaml").write_text("project_id: '1'\n")
            (Path(d2) / "jira.yaml").write_text("project_id: '2'\n")
            register_aspect("jira")
            self.assertEqual(aspect_files("jira", f"{d1}{os.pathsep}{d2}"),
                             [Path(d1) / "jira.yaml", Path(d2) / "jira.yaml"])
            with self.assertLogs(level="WARNING"):
                self.assertEqual(sole_aspect_file("jira", f"{d1}{os.pathsep}{d2}"),
                                 Path(d1) / "jira.yaml")

    def test_a_registered_aspect_gets_the_shape_rule_too(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "jira").mkdir()
            register_aspect("jira")          # file-only, by default
            with self.assertRaises(ConfigError):
                aspect_in(root, "jira")

    def test_a_builtin_aspect_cannot_be_redefined(self):
        with self.assertLogs(level="WARNING") as logs:
            register_aspect("users", as_file=False, as_directory=True)
        self.assertNotIn("users", registered_aspects())
        self.assertTrue(any("config/users.yaml" in line for line in logs.output))
        # …and the built-in two-form shape still holds.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users").mkdir()
            self.assertEqual(aspect_in(root, "users"), root / "users")
            (root / "users.yaml").write_text("admin: {password: a}\n")
            with self.assertRaises(ConfigError):
                aspect_in(root, "users")

    def test_a_name_that_is_not_a_bare_stem_is_refused(self):
        for name in ("../escape", "sub/dir", "Jira", "", "9lives"):
            with self.assertLogs(level="WARNING"):
                register_aspect(name)
        self.assertEqual(registered_aspects(), ())

    def test_an_aspect_that_can_take_no_form_is_refused(self):
        with self.assertLogs(level="WARNING"):
            register_aspect("jira", as_file=False, as_directory=False)
        self.assertEqual(registered_aspects(), ())

    def test_the_first_registration_of_a_name_wins(self):
        register_aspect("jira")
        with self.assertLogs(level="WARNING"):
            register_aspect("jira", as_file=False, as_directory=True)
        self.assertEqual(ASPECTS["jira"].shape(), "config/jira.yaml")
        # An identical repeat is not a conflict and says nothing.
        with self.assertNoLogs(level="WARNING"):
            register_aspect("jira")

    def test_registered_aspects_are_reported_and_can_be_forgotten(self):
        register_aspect("jira")
        self.assertEqual(registered_aspects(), ("jira",))
        forget_aspects()
        self.assertEqual(registered_aspects(), ())
        self.assertIn("users", ASPECTS)
