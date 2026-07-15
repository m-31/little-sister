import tempfile
import unittest
from pathlib import Path
from unittest import TestCase
from zoneinfo import ZoneInfo

from little_sister.config import DEFAULT_TIMEZONE, load_config


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


if __name__ == "__main__":
    unittest.main()
