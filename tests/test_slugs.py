"""`slug()` — the declared-slug helper a check builds from provider identifiers.

The counterpart of `derived_slug`'s content hash (ADR-0036), and the rule it
enforces is ADR-0050's: identity comes from the provider, never from the rendered
text and never from a position.
"""
from __future__ import annotations

import pytest

from little_sister.reasons import MAX_SLUG_LENGTH, ReasonError, normalize, slug


def test_parts_join_into_a_readable_token():
    assert slug("alpha", "pr", 42) == "alpha-pr-42"


def test_unsafe_characters_collapse():
    """A branch name carries `/`, an entity name carries spaces — neither may reach
    a `?reason=` value unencoded."""
    assert slug("alpha", "workflow", 7, "feature/new thing") == \
        "alpha-workflow-7-feature-new-thing"


def test_empty_parts_leave_no_dangling_separator():
    assert slug("alpha", "", "sbom") == "alpha-sbom"
    assert slug("alpha", "issue", 0) == "alpha-issue-0"   # a real 0 is still a part


def test_a_missing_part_is_none_and_drops_out():
    """`*parts: object` takes a `str | None` branch without a murmur from mypy, so
    the absent case has to be handled here: `str(None)` would put the literal token
    `None` in the slug, and every entity missing that field would share it."""
    assert slug("alpha", None, "pr", 1) == "alpha-pr-1"
    assert slug("alpha", None) == "alpha"


def test_a_part_that_keeps_nothing_is_hashed_rather_than_dropped():
    """The narrowing is ASCII-only, so a Japanese or Cyrillic entity name would
    otherwise *vanish* — two findings collapsing onto one slug, told apart by
    `_dedupe` by their position in the list. That is the failure ADR-0050 exists to
    prevent, so a part that had something keeps something."""
    first = slug("security", "日本語")
    second = slug("security", "★")

    assert first != second
    assert first != "security" and second != "security"
    assert first.startswith("security-")
    assert slug("security", "日本語") == first   # and it is stable


def test_a_slug_of_only_blank_parts_is_a_call_site_bug():
    with pytest.raises(ValueError):
        slug("", "  ", None)


def test_punctuation_that_keeps_nothing_is_data_and_is_hashed():
    """`///` is not blank — something was there. Dropping it is the vanish bug in
    miniature, so it hashes like any other part that keeps nothing."""
    assert slug("///") != slug("...")


def test_an_over_long_slug_keeps_a_prefix_and_a_hash_of_the_whole():
    """Truncation alone would map two long names onto one slug — and little-sister
    would then tell them apart *by position*, the one thing a slug outlives."""
    first = slug("r" * 300, "pr", 1)
    second = slug("r" * 300 + "-other", "pr", 1)
    assert len(first) == MAX_SLUG_LENGTH
    assert first != second
    assert first.startswith("r" * 100)


def test_the_result_is_a_slug_little_sister_accepts():
    """The whole point: what comes out survives `normalize`, which is where a bad
    slug would otherwise surface as a failing check."""
    entries, members = normalize({slug("an alpha", "pr", 1): "text"})
    assert members
    assert entries[0].slug == "an-alpha-pr-1"


def test_a_control_character_never_survives():
    try:
        normalize({slug("al\x07pha", "pr", 1): "text"})
    except ReasonError:                     # pragma: no cover - would be the bug
        pytest.fail("slug() let a control character through")


def test_a_first_part_of_h_reads_as_derived():
    """The documented overlap: `Entry.derived` asks whether a slug *starts with*
    `h-`, so a declared slug whose first part is `h` answers yes. Pinned here so
    the caveat in the docstring is a measured fact rather than a warning."""
    entries, _ = normalize({slug("h", "alpha", 1): "text"})
    assert entries[0].slug == "h-alpha-1"
    assert entries[0].derived
