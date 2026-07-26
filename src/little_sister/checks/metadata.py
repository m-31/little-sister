"""Per-subnode display metadata (``title`` / ``about``) from a check's own config.

A branch check's aspect leaves are **type-inherent** (ADR-0025), so their labels can
live **with the check** rather than be copy-pasted into ``nodes.yaml``. A check reads a
``subnodes:`` block from its config — ``name -> {title, about}`` — in the same file its
root ``about`` / ``title`` live in, and passes each through on the matching child
``CheckResult`` (Phase-4 fill-empty carries it; ``nodes.yaml`` still overrides per path,
as a last resort). A check that also ships built-in defaults (e.g. ``host-metrics``'
per-aspect ``about``) uses the config value when present and falls back to its default.

:func:`expand_tokens` lets a label reuse a value the check already holds (e.g. an
``org``) or owns (a severity legend) via ``{token}`` placeholders — a plain
:func:`str.replace`, never ``str.format``, so backticks, braces and other Markdown in
the text stay intact.
"""
from __future__ import annotations

from typing import Any

from little_sister.checks.base import CheckError


def parse_subnodes(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Parse a check config's optional ``subnodes:`` map — ``name -> {title, about}``
    — into ``{name: {"title": …, "about": …}}``. A missing block is ``{}``; a
    malformed one raises :class:`CheckError`, so a typo fails the load loudly."""
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> {title, about}")
    parsed: dict[str, dict[str, str]] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with 'title' / 'about'")
        parsed[str(name)] = {"title": str(meta.get("title", "")),
                             "about": str(meta.get("about", ""))}
    return parsed


def expand_tokens(text: str, tokens: dict[str, str]) -> str:
    """Substitute ``{key}`` for each token via a plain replace (**not**
    ``str.format``), so backticks and stray braces in the Markdown are untouched.
    An unknown ``{token}`` is simply left as-is."""
    for key, value in tokens.items():
        text = text.replace("{" + key + "}", value)
    return text
