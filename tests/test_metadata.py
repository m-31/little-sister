"""Tests for the `subnodes:` block's readers — all of them the library's own.

Since ADR-0025's 2026-08-19 update no name in `checks.metadata` is on the
check-authoring surface: `_parse_common` reads the block for every type and
`Check.__init__` resolves the labels, so these are internals with one caller
each. What a *check* now declares instead is tested in `test_checks.py`
(`SubnodeLabelTests`) and what the engine does with it in `test_engine.py`.
"""
from __future__ import annotations

import unittest
from unittest import TestCase

from little_sister.checks.base import CheckError
from little_sister.checks.metadata import (
    expand_tokens,
    parse_show_when_quiet,
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


class ParseShowWhenQuietTests(TestCase):
    """The second reader over the `subnodes:` block (ADR-0063) — the library's
    reader: `_parse_common` runs it for every type, so no check calls it."""

    def test_reads_a_stated_true_and_a_stated_false(self):
        parsed = parse_show_when_quiet({"subnodes": {
            "ec2": {"show_when_quiet": True},
            "cloudwatch": {"show_when_quiet": False}}})
        self.assertEqual(parsed, {"ec2": True, "cloudwatch": False})

    def test_a_name_that_says_nothing_is_absent_from_the_result(self):
        # Absence is the tri-state's third value: for a name this omits, the
        # engine falls back to the child result's shipped default, and a
        # nodes.yaml seed still beats both.
        parsed = parse_show_when_quiet({"subnodes": {
            "ec2": {"about": "the inventory"},
            "batch": {"show_when_quiet": False}}})
        self.assertEqual(parsed, {"batch": False})
        self.assertNotIn("ec2", parsed)

    def test_missing_block_is_empty(self):
        self.assertEqual(parse_show_when_quiet({}), {})

    def test_a_non_boolean_is_refused(self):
        with self.assertRaises(CheckError) as caught:
            parse_show_when_quiet({"subnodes": {"ec2": {"show_when_quiet": "false"}}})
        self.assertIn("subnodes.ec2.show_when_quiet", str(caught.exception))
        self.assertIn("true or false", str(caught.exception))

    def test_rejects_non_mapping(self):
        with self.assertRaises(CheckError):
            parse_show_when_quiet({"subnodes": ["not", "a", "map"]})
        with self.assertRaises(CheckError):
            parse_show_when_quiet({"subnodes": {"ec2": "just a string"}})

    def test_leaves_the_label_reader_alone(self):
        # Why this is a second reader and not a third key: `parse_subnodes`'
        # values stay strings, so a check scanning or layering them cannot meet a
        # bool it has never heard of.
        config = {"subnodes": {"ec2": {"about": "the inventory",
                                       "show_when_quiet": True}}}
        self.assertEqual(parse_subnodes(config),
                         {"ec2": {"title": "", "about": "the inventory"}})


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


class RetiredFromTheFacadeTests(TestCase):
    """The breaking half of the update: these three left `little_sister.checks`.

    Stated here as well as in the surface guard because the guard is about the doc
    and the code agreeing, while this is about the names being *gone* — the thing a
    plugin built for check API epoch 1 will find at import time.
    """

    def test_the_three_helpers_are_off_the_check_facade(self):
        import little_sister.checks as facade

        for name in ("parse_subnodes", "resolve_text", "expand_tokens"):
            with self.subTest(name=name):
                self.assertNotIn(name, facade.__all__)
                self.assertFalse(hasattr(facade, name))

    def test_the_epoch_moved_with_them(self):
        # Removing a promised name is what API_VERSION is for (ADR-0051): a
        # package built for the epoch that had them refuses at startup instead of
        # raising an ImportError from inside somebody else's __init__.
        from little_sister.checks import API_VERSION

        self.assertGreaterEqual(API_VERSION, 2)


if __name__ == "__main__":
    unittest.main()
