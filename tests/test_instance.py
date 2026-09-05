"""This instance's mark (ADR-0074): what it is made of, and what it refuses.

The parts are pinned rather than the whole string, because the mark is compared
for equality and printed and **never parsed** — a test that asserted a joined
format would be promising a format nothing else promises.
"""
import os
import re
import unittest
from dataclasses import replace
from unittest import TestCase, mock

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instance as instance_module
from little_sister import self_report
from little_sister.instance import MAX_NAME, Instance, resolve, this_instance


class TheMarkTests(TestCase):
    def test_it_names_a_process_and_when_it_started(self):
        mark = Instance(name="web-1", pid=17, started="20260905T090000Z",
                        tag="2b7de044").mark

        self.assertEqual(mark, "web-1:17:20260905T090000Z:2b7de044")

    def test_the_start_carries_no_colon_of_its_own(self):
        """The parts are joined with ':', so the extended ISO form — which has
        three colons in it — would make one mark read as four."""
        self.assertNotIn(":", this_instance().started)
        self.assertRegex(this_instance().started, r"\A\d{8}T\d{6}Z\Z")

    def test_two_processes_never_share_a_mark(self):
        """The tag is what makes an equality test on the mark sound. Two
        containers of one deployment share a configured name, run as pid 1 and
        start in the same second — the whole of what separates them is this."""
        marks = {resolve().mark for _ in range(50)}

        self.assertEqual(len(marks), 50)

    def test_the_tag_is_eight_hex_characters(self):
        self.assertRegex(this_instance().tag, r"\A[0-9a-f]{8}\Z")

    def test_it_is_resolved_once_and_does_not_move(self):
        """A mark that changed mid-process would break the only thing it is for."""
        self.assertIs(this_instance(), this_instance())

    def test_importing_the_module_reads_no_configuration(self):
        """A package that imports this in its own module body must not thereby
        need a configuration root at import time — `little-sister-aws` does exactly
        that. So the settings are reached inside `resolve` and nowhere else."""
        import ast
        from pathlib import Path

        source = Path(instance_module.__file__).read_text()
        top_level = [node for node in ast.parse(source).body
                     if isinstance(node, ast.ImportFrom)]

        self.assertNotIn("little_sister.config",
                         [node.module for node in top_level])


class TheConfiguredNameTests(TestCase):
    """`instance:` in settings.yaml, and the hostname where it says nothing."""

    def setUp(self):
        self_report.startup.forget()

    def tearDown(self):
        self_report.startup.forget()

    def _resolved(self, name, host="a-host"):
        # `little_sister.config.config` rather than an attribute of the module
        # under test: `resolve()` imports it at call time, on purpose, so that
        # importing this module reads no configuration. What a refusal says is a
        # standing note on the self-report seam, read back from there.
        from little_sister.config import config

        with mock.patch("little_sister.config.config",
                        replace(config, instance=name)), \
                mock.patch("little_sister.instance.socket.gethostname",
                           return_value=host):
            resolved = resolve()
        return resolved, " ".join(line.text for line in self_report.startup.lines())

    def test_a_name_the_deployment_chose_is_used(self):
        resolved, noted = self._resolved("web-frontend")

        self.assertEqual(resolved.name, "web-frontend")
        self.assertEqual(noted, "")

    def test_no_name_is_the_hostname(self):
        resolved, _ = self._resolved("", host="ip-10-0-3-14")

        self.assertEqual(resolved.name, "ip-10-0-3-14")

    def test_surrounding_whitespace_is_not_part_of_the_name(self):
        resolved, _ = self._resolved("  web-frontend  ")

        self.assertEqual(resolved.name, "web-frontend")

    def test_a_name_written_and_left_empty_falls_back_and_says_so(self):
        resolved, noted = self._resolved("   ")

        self.assertEqual(resolved.name, "a-host")
        self.assertIn("left empty", noted)

    def test_a_name_carrying_the_separator_is_refused(self):
        """It would make one mark read as five parts, and the reader that
        compares marks would be comparing something else."""
        resolved, noted = self._resolved("web:frontend")

        self.assertEqual(resolved.name, "a-host")
        self.assertIn("may not contain", noted)

    def test_a_name_carrying_whitespace_is_refused(self):
        resolved, _ = self._resolved("web frontend")

        self.assertEqual(resolved.name, "a-host")

    def test_a_name_longer_than_the_cap_is_refused(self):
        resolved, noted = self._resolved("x" * (MAX_NAME + 1))

        self.assertEqual(resolved.name, "a-host")
        self.assertIn("longer than", noted)

    def test_a_name_exactly_at_the_cap_is_kept(self):
        resolved, _ = self._resolved("x" * MAX_NAME)

        self.assertEqual(resolved.name, "x" * MAX_NAME)

    def test_a_refusal_never_stops_the_start(self):
        """Nothing about the name is load-bearing — the tag carries the
        uniqueness — so refusing to start over a cosmetic label would make the
        mark more dangerous than not having one."""
        resolved, _ = self._resolved("web:frontend")

        self.assertTrue(resolved.mark)
        self.assertRegex(resolved.mark, r"\A[^:]+:\d+:\d{8}T\d{6}Z:[0-9a-f]{8}\Z")


class TheSettingTests(TestCase):
    def test_it_arrives_from_the_settings_file(self):
        import tempfile
        from pathlib import Path

        from little_sister.config import load_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("instance: web-frontend\n")

            self.assertEqual(load_config(path).instance, "web-frontend")

    def test_it_defaults_to_nothing_said(self):
        import tempfile
        from pathlib import Path

        from little_sister.config import load_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("timezone: UTC\n")

            self.assertEqual(load_config(path).instance, "")


class TheSystemPageTests(TestCase):
    """Which installation this is, on the one page that lists what is installed."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _page(self):
        return self.client.get("/system").get_data(as_text=True)

    def test_the_page_carries_this_instance_s_mark(self):
        self.assertIn(this_instance().mark, self._page())

    def test_it_says_when_the_name_is_only_the_hostname(self):
        with mock.patch.object(app_module, "this_instance", lambda:
                               Instance(name="a-host", pid=1,
                                        started="20260905T090000Z",
                                        tag="2b7de044")), \
                mock.patch.object(app_module, "config",
                                  replace(app_module.config, instance="")):
            page = self._page()

        self.assertIn("a-host:1:20260905T090000Z:2b7de044", page)
        self.assertIn("the hostname", page)

    def test_a_configured_name_is_not_explained_away(self):
        with mock.patch.object(app_module, "this_instance", lambda:
                               Instance(name="web-frontend", pid=1,
                                        started="20260905T090000Z",
                                        tag="2b7de044")), \
                mock.patch.object(app_module, "config",
                                  replace(app_module.config,
                                          instance="web-frontend")):
            page = self._page()

        self.assertIn("web-frontend", page)
        self.assertNotIn("the hostname", page)

    def test_the_block_is_outside_the_polled_fragment(self):
        """It is settled at import and cannot change while the process runs, which
        is the rule that block states for itself — re-sending it ten times a
        minute would be sending a constant."""
        fragment = self.client.get("/system?fragment=1").get_data(as_text=True)

        self.assertNotIn(this_instance().mark, fragment)


assert re.match(r"\A[^:]+:\d+:\d{8}T\d{6}Z:[0-9a-f]{8}\Z", this_instance().mark), \
    "the module's own mark has the shape this file is about"

if __name__ == "__main__":
    unittest.main()
