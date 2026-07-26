"""Tests for the shared subnode-metadata helpers."""
from __future__ import annotations

import unittest
from unittest import TestCase

from little_sister.checks.base import CheckError
from little_sister.checks.metadata import expand_tokens, parse_subnodes


class ParseSubnodesTests(TestCase):
    def test_reads_title_and_about(self):
        parsed = parse_subnodes({"subnodes": {
            "disk": {"title": "Disk", "about": "Free space."}}})
        self.assertEqual(parsed, {"disk": {"title": "Disk", "about": "Free space."}})

    def test_missing_is_empty(self):
        self.assertEqual(parse_subnodes({}), {})

    def test_rejects_non_mapping(self):
        with self.assertRaises(CheckError):
            parse_subnodes({"subnodes": ["not", "a", "map"]})
        with self.assertRaises(CheckError):
            parse_subnodes({"subnodes": {"disk": "just a string"}})


class ExpandTokensTests(TestCase):
    def test_is_a_plain_replace(self):
        # backticks and stray braces in the Markdown survive; an unknown token stays
        text = "org={org}; `code {with braces}`; {unknown} stays"
        out = expand_tokens(text, {"org": "otto-ec"})
        self.assertEqual(out, "org=otto-ec; `code {with braces}`; {unknown} stays")


if __name__ == "__main__":
    unittest.main()
