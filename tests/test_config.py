import os
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase
from zoneinfo import ZoneInfo

from little_sister.config import (
    DEFAULT_BRANCH_CAP,
    DEFAULT_MAINTENANCE_CAP,
    DEFAULT_MAX_WORKERS,
    DEFAULT_STATE_INTERVAL,
    DEFAULT_TIMEZONE,
    ENTRY_LIMIT,
    MEMORY_SHARE,
    load_config,
)


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


if __name__ == "__main__":
    unittest.main()
