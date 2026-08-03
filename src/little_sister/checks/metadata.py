"""Per-subnode display metadata (``title`` / ``about``) from a check's own config.

A branch check's aspect leaves are **type-inherent** (ADR-0025), so their labels can
live **with the check** rather than be copy-pasted into ``nodes.yaml``. A check reads a
``subnodes:`` block from its config — ``name -> {title, about}`` — in the same file its
root ``about`` / ``title`` live in, and passes each through on the matching child
``CheckResult`` (Phase-4 fill-empty carries it; ``nodes.yaml`` still overrides per path,
as a last resort). A check that also ships built-in defaults (e.g. ``host-metrics``'
per-aspect ``about``) layers the two with :func:`resolve_text`: the config value when
present, the default otherwise — and the config may **extend** the default rather than
replace it by writing ``{default}`` into its own text. That keeps text that is inherent
to the check *type* in one place while a deployment still has the last word, which
matters most when one check type runs several times (one per team) and would otherwise
have the same paragraphs copy-pasted into every instance's config.

:func:`expand_tokens` lets a label reuse a value the check already holds (e.g. an
``org``) or owns (a severity legend) via ``{token}`` placeholders — a plain
:func:`str.replace`, never ``str.format``, so backticks, braces and other Markdown in
the text stay intact.
"""
from __future__ import annotations

from typing import Any

from little_sister import values
from little_sister.errors import CheckError


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
        parsed[str(name)] = {"title": values.text(meta, "title"),
                             "about": values.text(meta, "about")}
    return parsed


def resolve_text(configured: str, default: str,
                 tokens: dict[str, str] | None = None) -> str:
    """One label's final text: the check's built-in ``default``, what its config
    says, or both.

    An empty ``configured`` yields the default. Otherwise the config text wins —
    except that a ``{default}`` placeholder in it is replaced by the default, so a
    deployment can **extend** the shipped text (before it, after it, around it)
    instead of restating it. The substitution happens *before* :func:`expand_tokens`,
    so ``{token}`` placeholders inside the default text expand too; an aspect with no
    default resolves ``{default}`` to nothing rather than leaving the literal token
    on a dashboard.
    """
    text = configured if configured.strip() else default
    text = text.replace("{default}", default)
    return expand_tokens(text, tokens or {})


def expand_tokens(text: str, tokens: dict[str, str]) -> str:
    """Substitute ``{key}`` for each token via a plain replace (**not**
    ``str.format``), so backticks and stray braces in the Markdown are untouched.
    An unknown ``{token}`` is simply left as-is."""
    for key, value in tokens.items():
        text = text.replace("{" + key + "}", value)
    return text
