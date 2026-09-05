"""A title that only repeats its name is not drawn (`little_sister.titles`)."""
from unittest import TestCase

from little_sister.titles import decorative, label_parts, shown_title


class ShownTitleTests(TestCase):
    def test_no_title_is_no_title(self):
        self.assertEqual(shown_title("critical", ""), "")
        self.assertEqual(shown_title("critical", None), "")

    def test_the_capitalized_name_is_dropped(self):
        # The case this phase exists for: `github` / `wiz` severity bands, whose
        # chips read `critical Critical` today.
        for name in ("critical", "high", "medium", "low", "none", "informational"):
            with self.subTest(name=name):
                self.assertEqual(shown_title(name, name.capitalize()), "")

    def test_an_identifier_and_its_sentence_are_one_string(self):
        # `_`, `-` and a space are the same separator, and case is folded, so all
        # of these say exactly what the name says.
        self.assertEqual(shown_title("pull_requests", "Pull requests"), "")
        self.assertEqual(shown_title("pull_requests", "Pull Requests"), "")
        self.assertEqual(shown_title("pull_requests", "pull-requests"), "")
        self.assertEqual(
            shown_title("code_scanning_alerts", "Code-scanning alerts"), "")
        self.assertEqual(shown_title("disk", "  disk  "), "")
        self.assertEqual(shown_title("host metrics", "Host   Metrics"), "")

    def test_a_title_that_adds_anything_survives(self):
        self.assertEqual(shown_title("disk", "Disk usage"), "Disk usage")
        self.assertEqual(shown_title("cpu", "Load"), "Load")
        self.assertEqual(shown_title("build", "build #42"), "build #42")
        # Punctuation other than the separators is a difference, not typography.
        self.assertEqual(shown_title("none", "None?"), "None?")

    def test_the_comparison_is_on_the_raw_markdown(self):
        # Deliberate: the fold runs before the inline renderer (ADR-0018), so it is
        # one string comparison and not a question about rendered HTML.
        self.assertEqual(shown_title("critical", "**Critical**"), "**Critical**")

    def test_underscore_emphasis_folds_and_asterisk_emphasis_does_not(self):
        # The documented asymmetry, pinned so it stays a decision rather than a
        # surprise: `_` is a separator to this rule *and* an emphasis marker to
        # Markdown, so `_critical_` reduces to the name and goes; `**Critical**`
        # does not, and stays. See the module docstring for why the difference is
        # left alone rather than chased with a Markdown parse.
        self.assertEqual(shown_title("critical", "_critical_"), "")
        self.assertEqual(shown_title("critical", "*critical*"), "*critical*")

    def test_the_name_is_folded_too_not_only_the_title(self):
        # A `nodes.yaml` name may itself be a sentence; the rule is symmetric.
        self.assertEqual(shown_title("Pull Requests", "pull_requests"), "")

    def test_folding_never_merges_two_different_words(self):
        self.assertEqual(shown_title("low", "medium"), "medium")
        self.assertEqual(shown_title("disk", "disks"), "disks")
        self.assertEqual(shown_title("a_b", "ab"), "ab")


class DecorativeTests(TestCase):
    """A title with no word in it (ADR-0061)."""

    def test_a_glyph_is_decoration(self):
        for title in ("🔴", "🟠", "🟢", "❓", "→", "…", "★", "•", "⚠️"):
            with self.subTest(title=title):
                self.assertTrue(decorative(title))

    def test_a_word_in_any_script_is_a_word(self):
        # `isalnum`, not an ASCII test: the rule is *is there a word here*, and a
        # word is not only a Latin one.
        for title in ("Critical", "日本語", "Кластер", "Δίσκος", "42", "v2"):
            with self.subTest(title=title):
                self.assertFalse(decorative(title))

    def test_one_letter_anywhere_is_enough(self):
        # The test is not *is this mostly a glyph*. A title that carries a word at
        # all can stand in for a name, which is all this predicate decides.
        self.assertFalse(decorative("🔴 Critical"))
        self.assertFalse(decorative("→ 2"))


class LabelPartsTests(TestCase):
    """What to draw where a surface draws the title instead of the name."""

    def test_a_word_still_stands_in_for_the_name(self):
        # Unchanged behavior, and the reason the rule is narrow: a node titled
        # `Cluster A` is better named that way in a pasted document.
        self.assertEqual(label_parts("web", "Cluster A"), ("", "Cluster A"))

    def test_a_glyph_comes_with_its_name_rather_than_instead_of_it(self):
        # The whole point. Drawn in the chip's own order — name first, title after.
        self.assertEqual(label_parts("critical", "🔴"), ("critical", "🔴"))
        self.assertEqual(label_parts("high", "🟠"), ("high", "🟠"))

    def test_a_title_that_only_repeats_the_name_leaves_the_name_alone(self):
        # The first rule runs first: `Critical` folds away, and what is left is a
        # name with no title — not a name with a decoration beside it.
        self.assertEqual(label_parts("critical", "Critical"), ("critical", ""))
        self.assertEqual(label_parts("critical", None), ("critical", ""))
        self.assertEqual(label_parts("critical", ""), ("critical", ""))
