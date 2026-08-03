"""Tests for the shared subnode-metadata helpers."""
from __future__ import annotations

import unittest
from unittest import TestCase

from little_sister.checks.base import CheckError
from little_sister.checks.metadata import (
    expand_tokens,
    parse_subnodes,
    resolve_text,
)


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
        out = expand_tokens(text, {"org": "linux"})
        self.assertEqual(out, "org=linux; `code {with braces}`; {unknown} stays")


class ResolveTextTests(TestCase):
    """The config's text layered over a check type's built-in default (ADR-0025)."""

    DEFAULT = "Open pull requests on {team}'s repositories."

    def test_no_config_gives_the_default(self):
        self.assertEqual(resolve_text("", self.DEFAULT, {"team": "security"}),
                         "Open pull requests on security's repositories.")

    def test_blank_config_gives_the_default(self):
        self.assertEqual(resolve_text("   \n", self.DEFAULT, {"team": "q"}),
                         "Open pull requests on q's repositories.")

    def test_config_without_the_token_overwrites(self):
        self.assertEqual(resolve_text("Ours instead.", self.DEFAULT, {"team": "q"}),
                         "Ours instead.")

    def test_config_with_the_token_extends_after(self):
        self.assertEqual(
            resolve_text("{default}\n\nAlso ping #oncall.", self.DEFAULT,
                         {"team": "security"}),
            "Open pull requests on security's repositories.\n\nAlso ping #oncall.")

    def test_config_with_the_token_extends_before(self):
        self.assertEqual(
            resolve_text("Triage daily.\n\n{default}", "Base.", {}),
            "Triage daily.\n\nBase.")

    def test_config_may_wrap_the_default(self):
        self.assertEqual(resolve_text("A {default} B", "mid", {}), "A mid B")

    def test_token_inside_the_default_expands_through_the_extension(self):
        """The default is substituted first, so its own tokens still expand."""
        self.assertEqual(resolve_text("{default} — {team}", self.DEFAULT,
                                      {"team": "security"}),
                         "Open pull requests on security's repositories. — security")

    def test_no_default_resolves_the_token_to_nothing(self):
        """Never leave a literal {default} on a dashboard."""
        self.assertEqual(resolve_text("Only ours. {default}", "", {}), "Only ours. ")

    def test_tokens_are_optional(self):
        self.assertEqual(resolve_text("plain", "d"), "plain")

    def test_unknown_token_is_left_alone(self):
        self.assertEqual(resolve_text("{nope}", "d", {"team": "q"}), "{nope}")


if __name__ == "__main__":
    unittest.main()
