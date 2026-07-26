import tempfile
import unittest
from pathlib import Path
from unittest import TestCase
from zoneinfo import ZoneInfo

from little_sister.config import (
    DEFAULT_BRANCH_CAP,
    DEFAULT_MAINTENANCE_CAP,
    DEFAULT_TIMEZONE,
    load_config,
)


class ConfigTests(TestCase):
    def test_missing_file_uses_defaults(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertEqual(cfg.timezone, DEFAULT_TIMEZONE)
        self.assertIsInstance(cfg.tzinfo, ZoneInfo)

    def test_reads_options(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text('timezone: UTC\ntime_format: "%H:%M"\n')
            cfg = load_config(path)
            self.assertEqual(cfg.timezone, "UTC")
            self.assertEqual(cfg.time_format, "%H:%M")

    def test_invalid_timezone_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("timezone: Not/AZone\n")
            self.assertEqual(load_config(path).timezone, DEFAULT_TIMEZONE)

    def test_reads_branch_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("branch_cap: 5\n")
            self.assertEqual(load_config(path).branch_cap, 5)

    def test_branch_cap_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("timezone: UTC\n")            # key absent → the default
            self.assertEqual(load_config(path).branch_cap, DEFAULT_BRANCH_CAP)

    def test_invalid_branch_cap_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("branch_cap: lots\n")
            self.assertEqual(load_config(path).branch_cap, DEFAULT_BRANCH_CAP)

    def test_negative_branch_cap_clamped_to_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("branch_cap: -2\n")
            self.assertEqual(load_config(path).branch_cap, 0)

    def test_reads_maintenance_cap(self):
        # slice 10: the pill popover's count-cap, read like branch_cap
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("maintenance_cap: 8\n")
            self.assertEqual(load_config(path).maintenance_cap, 8)

    def test_maintenance_cap_defaults_when_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("timezone: UTC\n")            # key absent → the default
            self.assertEqual(
                load_config(path).maintenance_cap, DEFAULT_MAINTENANCE_CAP)

    def test_invalid_maintenance_cap_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("maintenance_cap: heaps\n")
            self.assertEqual(
                load_config(path).maintenance_cap, DEFAULT_MAINTENANCE_CAP)

    def test_negative_maintenance_cap_clamped_to_zero(self):
        # 0 is meaningful — it sends every pin straight to the /maintenance page
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("maintenance_cap: -3\n")
            self.assertEqual(load_config(path).maintenance_cap, 0)


if __name__ == "__main__":
    unittest.main()
