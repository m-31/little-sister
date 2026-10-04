import logging
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase
from zoneinfo import ZoneInfo

import little_sister.logger
from little_sister.config import (
    DEFAULT_BRANCH_CAP,
    DEFAULT_MAINTENANCE_CAP,
    DEFAULT_MAX_WORKERS,
    DEFAULT_READING_CAP,
    DEFAULT_STATE_INTERVAL,
    DEFAULT_TIMEZONE,
    ENTRY_LIMIT,
    MEMORY_SHARE,
    RECORD_LIMIT,
    load_config,
)
from tests.running import subprocess_env


class StacktraceOptionTests(TestCase):
    def test_defaults_on(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertIs(cfg.stacktrace, True)

    def test_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("stacktrace: false\n")
            self.assertIs(load_config(path).stacktrace, False)


class ConfigTests(TestCase):
    def test_missing_file_uses_defaults(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertEqual(cfg.timezone, DEFAULT_TIMEZONE)
        self.assertIsInstance(cfg.tzinfo, ZoneInfo)

    def test_reads_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text('timezone: UTC\ntime_format: "%H:%M"\n')
            cfg = load_config(path)
            self.assertEqual(cfg.timezone, "UTC")
            self.assertEqual(cfg.time_format, "%H:%M")

    def test_invalid_timezone_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("timezone: Not/AZone\n")
            self.assertEqual(load_config(path).timezone, DEFAULT_TIMEZONE)

    def test_reads_branch_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("branch_cap: 5\n")
            self.assertEqual(load_config(path).branch_cap, 5)

    def test_branch_cap_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("timezone: UTC\n")            # key absent → the default
            self.assertEqual(load_config(path).branch_cap, DEFAULT_BRANCH_CAP)

    def test_invalid_branch_cap_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("branch_cap: lots\n")
            self.assertEqual(load_config(path).branch_cap, DEFAULT_BRANCH_CAP)

    def test_negative_branch_cap_clamped_to_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("branch_cap: -2\n")
            self.assertEqual(load_config(path).branch_cap, 0)

    def test_reads_maintenance_cap(self):
        # the pill popover's count-cap, read like branch_cap
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("maintenance_cap: 8\n")
            self.assertEqual(load_config(path).maintenance_cap, 8)

    def test_maintenance_cap_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("timezone: UTC\n")            # key absent → the default
            self.assertEqual(
                load_config(path).maintenance_cap, DEFAULT_MAINTENANCE_CAP)

    def test_invalid_maintenance_cap_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("maintenance_cap: heaps\n")
            self.assertEqual(
                load_config(path).maintenance_cap, DEFAULT_MAINTENANCE_CAP)

    def test_negative_maintenance_cap_clamped_to_zero(self):
        # 0 is meaningful — it sends every pin straight to the /maintenance page
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("maintenance_cap: -3\n")
            self.assertEqual(load_config(path).maintenance_cap, 0)

    def test_reading_cap_is_ten_by_default(self):
        # how many of a subject's readings its node shows (ADR-0092 decision 7)
        self.assertEqual(DEFAULT_READING_CAP, 10)
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertEqual(cfg.reading_cap, 10)

    def test_reads_reading_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("reading_cap: 25\n")
            self.assertEqual(load_config(path).reading_cap, 25)

    def test_a_reading_cap_of_zero_is_kept(self):
        # 0 shows the curves alone and leaves every reading to the History page
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("reading_cap: 0\n")
            self.assertEqual(load_config(path).reading_cap, 0)

    def test_invalid_reading_cap_is_logged_and_defaulted(self):
        # a setting is logged and replaced, as every display cap's is (ADR-0006);
        # it is the check's own key that refuses the start
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("reading_cap: plenty\n")
            with self.assertLogs("little_sister", level="WARNING") as logged:
                self.assertEqual(load_config(path).reading_cap,
                                 DEFAULT_READING_CAP)
            self.assertIn("reading_cap", "\n".join(logged.output))

    def test_negative_reading_cap_clamped_to_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("reading_cap: -4\n")
            self.assertEqual(load_config(path).reading_cap, 0)

    def test_card_status_line_defaults_beside(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertEqual(cfg.card_status_line, "beside")

    def test_card_status_line_reads_below(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("card_status_line: below\n")
            self.assertEqual(load_config(path).card_status_line, "below")

    def test_card_status_line_junk_falls_back_with_a_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("card_status_line: sideways\n")
            with self.assertLogs("little_sister", level="WARNING") as logs:
                cfg = load_config(path)
        self.assertEqual(cfg.card_status_line, "beside")
        self.assertTrue(any("card_status_line" in line for line in logs.output))

    def test_dashboard_columns_defaults_flow(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertEqual(cfg.dashboard_columns, "flow")

    def test_dashboard_columns_reads_plain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("dashboard_columns: plain\n")
            self.assertEqual(load_config(path).dashboard_columns, "plain")

    def test_dashboard_columns_junk_falls_back_with_a_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("dashboard_columns: masonry\n")
            with self.assertLogs("little_sister", level="WARNING") as logs:
                cfg = load_config(path)
        self.assertEqual(cfg.dashboard_columns, "flow")
        self.assertTrue(any("dashboard_columns" in line for line in logs.output))


class SettingsLayeringTests(TestCase):
    """The `settings` aspect layers across configuration roots (ADR-0031):
    shallow merge **per key**, later root wins. The file is a flat mapping of
    scalars, so "shallow" is the whole story."""

    def _root(self, directory: str, text: str) -> str:
        (Path(directory) / "settings.yaml").write_text(text)
        return directory

    def test_later_root_wins_per_key(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self._root(d1, "timezone: UTC\nreason_cap: 9\n")
            self._root(d2, "reason_cap: 2\n")
            cfg = load_config(config_dir=f"{d1}{os.pathsep}{d2}")
            # the site root moved one key; the base's other key still stands
            self.assertEqual(cfg.reason_cap, 2)
            self.assertEqual(cfg.timezone, "UTC")

    def test_a_root_without_settings_contributes_nothing(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self._root(d1, "reason_cap: 9\n")
            cfg = load_config(config_dir=f"{d1}{os.pathsep}{d2}")
            self.assertEqual(cfg.reason_cap, 9)

    def test_no_settings_anywhere_is_all_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = load_config(config_dir=directory)
            self.assertEqual(cfg.timezone, DEFAULT_TIMEZONE)
            self.assertEqual(cfg.branch_cap, DEFAULT_BRANCH_CAP)

    def test_a_broken_layer_costs_only_its_own_keys(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self._root(d1, "reason_cap: 9\n")
            self._root(d2, "timezone: [not, a, mapping]\n:::\n")
            with self.assertLogs(level="WARNING"):
                cfg = load_config(config_dir=f"{d1}{os.pathsep}{d2}")
            self.assertEqual(cfg.reason_cap, 9)


class StateIntervalTests(TestCase):
    """`state_interval` (ADR-0071): how often the kept state files are written."""

    def test_reads_the_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("state_interval: 15\n")
            self.assertEqual(load_config(path).state_interval, 15)

    def test_defaults_to_a_minute(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("timezone: UTC\n")
            self.assertEqual(load_config(path).state_interval, DEFAULT_STATE_INTERVAL)
            self.assertEqual(DEFAULT_STATE_INTERVAL, 60)

    def test_a_bad_or_non_positive_value_falls_back_with_a_warning(self):
        # a typo must not make the writer spin, or stop
        for value in ("often", "0", "-5"):
            with tempfile.TemporaryDirectory() as directory, self.subTest(value=value):
                path = Path(directory) / "settings.yaml"
                path.write_text(f"state_interval: {value}\n")
                with self.assertLogs(level="WARNING"):
                    self.assertEqual(load_config(path).state_interval,
                                     DEFAULT_STATE_INTERVAL)


class EngineSizingTests(TestCase):
    """`max_workers`, `entry_limit` and `memory_share` (ADR-0075): the three
    numbers the engine measures itself and its configuration against, which a
    deployment may state and which fall back to the constants in `limits.py`."""

    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text(text)
            return load_config(path)

    def test_reads_the_three(self):
        cfg = self._load("max_workers: 24\nentry_limit: 5000\nmemory_share: 0.25\n")
        self.assertEqual(cfg.max_workers, 24)
        self.assertEqual(cfg.entry_limit, 5000)
        self.assertEqual(cfg.memory_share, 0.25)

    def test_default_to_the_limits_constants(self):
        cfg = self._load("timezone: UTC\n")            # keys absent → the defaults
        self.assertEqual(cfg.max_workers, DEFAULT_MAX_WORKERS)
        self.assertEqual(cfg.entry_limit, ENTRY_LIMIT)
        self.assertEqual(cfg.memory_share, MEMORY_SHARE)
        self.assertEqual((DEFAULT_MAX_WORKERS, ENTRY_LIMIT, MEMORY_SHARE),
                         (8, 100_000, 0.5))

    def test_reads_the_record_limit_and_defaults_to_the_constant(self):
        # how heavy an entry's record may be: the deployment's answer to a refusal
        # it disagrees with, and 2 KB where it says nothing
        self.assertEqual(self._load("record_limit: 8192\n").record_limit, 8192)
        self.assertEqual(self._load("timezone: UTC\n").record_limit, RECORD_LIMIT)
        self.assertEqual(RECORD_LIMIT, 2_048)

    def test_a_bad_record_limit_falls_back_with_a_warning(self):
        # zero would refuse every record, including the ones this deployment
        # configured a check to gather
        for value in ("plenty", "0", "-16"):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(
                    self._load(f"record_limit: {value}\n").record_limit,
                    RECORD_LIMIT)

    def test_reads_the_escalation_count_and_defaults_to_one(self):
        # one is today's behavior: the counter arrives switched off
        self.assertEqual(self._load("escalate_after: 3\n").escalate_after, 3)
        self.assertEqual(self._load("timezone: UTC\n").escalate_after, 1)

    def test_a_bad_escalation_count_falls_back_with_a_warning(self):
        # zero would mean *never publish*, which is the one direction ADR-0032
        # rule 7 refuses outright
        for value in ("often", "0", "-1"):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(
                    self._load(f"escalate_after: {value}\n").escalate_after, 1)

    def test_a_bad_worker_ceiling_falls_back_with_a_warning(self):
        # a typo must not leave the engine with no thread to run a check on
        for value in ("many", "0", "-2"):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(self._load(f"max_workers: {value}\n").max_workers,
                                 DEFAULT_MAX_WORKERS)

    def test_a_bad_entry_limit_falls_back_with_a_warning(self):
        # a limit of zero would put the engine's own line past it before a check ran
        for value in ("lots", "0", "-1"):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(self._load(f"entry_limit: {value}\n").entry_limit,
                                 ENTRY_LIMIT)

    def test_a_memory_share_outside_the_fraction_falls_back_with_a_warning(self):
        # above one is a limit the process cannot reach without being killed first
        for value in ("half", "0", "-0.5", "1.5"):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(self._load(f"memory_share: {value}\n").memory_share,
                                 MEMORY_SHARE)

    def test_a_share_of_exactly_one_is_allowed(self):
        self.assertEqual(self._load("memory_share: 1\n").memory_share, 1.0)


class TheZoneIsHandedOverTests(TestCase):
    """The configuration hands the time zone to whoever asked, the moment it has
    read it (ADR-0120 decision 9): the process's own configuration hands it to the
    logger, so that what is logged of the settings after it is stamped in it."""

    def _load(self, text: str, *, tell: bool = True) -> list[str]:
        """What was handed over and what was logged while ``text`` was loaded, in
        the order it happened."""
        heard: list[str] = []

        class _Heard(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                heard.append(f"logged: {record.getMessage()}")

        said = logging.getLogger("little_sister.logger")
        handler, level = _Heard(), said.level
        said.addHandler(handler)
        said.setLevel(logging.INFO)
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.yaml"
                path.write_text(text)
                if tell:
                    load_config(path,
                                zone_read=lambda zone: heard.append(f"zone: {zone}"))
                else:
                    load_config(path)
        finally:
            said.removeHandler(handler)
            said.setLevel(level)
        return heard

    def test_it_is_handed_over_before_anything_is_logged_of_the_settings(self):
        heard = self._load("timezone: Asia/Kathmandu\nreason_cap: many\n")
        self.assertEqual(heard[0], "zone: Asia/Kathmandu")
        self.assertEqual(heard.count("zone: Asia/Kathmandu"), 1)
        self.assertTrue(heard[1].startswith(
            "logged: config: reason_cap 'many' is not an integer"), heard)
        self.assertTrue(heard[-1].startswith("logged: config: loaded "), heard)

    def test_an_unknown_zone_hands_over_the_default_and_then_says_so(self):
        heard = self._load("timezone: Not/AZone\n")
        self.assertEqual(heard[:2], [
            f"zone: {DEFAULT_TIMEZONE}",
            f"logged: config: unknown timezone 'Not/AZone'; using {DEFAULT_TIMEZONE}"])

    def test_a_load_that_names_nobody_to_tell_leaves_the_logs_stamp_alone(self):
        # a test, or a tool, that loads a settings file of its own does not move
        # the zone this process's log is stamped in
        before = little_sister.logger._zone
        heard = self._load("timezone: Asia/Kathmandu\n", tell=False)
        self.assertIs(little_sister.logger._zone, before)
        self.assertFalse([line for line in heard if line.startswith("zone: ")])

    def test_the_process_own_configuration_hands_it_to_the_logger(self):
        # in a process of its own, since this one's logger is reloaded by its tests
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("timezone: Asia/Kathmandu\n")
            done = subprocess.run(
                [sys.executable, "-c",
                 "import little_sister.config, little_sister.logger as said; "
                 "print(said._zone)"],
                env={**subprocess_env(), "LITTLE_SISTER_CONFIG": str(path)},
                capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "Asia/Kathmandu")


if __name__ == "__main__":
    unittest.main()
