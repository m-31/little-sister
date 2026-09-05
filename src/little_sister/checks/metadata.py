"""The ``subnodes:`` block a check config may carry — read by the **library**.

A branch check's aspect leaves are **type-inherent** (ADR-0025), so their labels can
live **with the check** rather than be copy-pasted into ``nodes.yaml``. A deployment
retunes one in the check's own config: a ``subnodes:`` block, ``name -> {title,
about, show_when_quiet}``, in the same file the root's ``about`` / ``title`` live in.

**Every reader here is the library's own.** ``Check._parse_common`` runs
:func:`parse_subnodes` and :func:`parse_show_when_quiet` for every check whatever its
type, ``Check.__init__`` resolves the labels against what the type *declared*
(``subnode_defaults`` / ``label_tokens``) through :func:`resolve_text`, and the engine
applies both per child name. So a deployment can write this block for any installed
branch check with no check release, and a check type reads none of it — the flag since
ADR-0063, the labels since its 2026-08-19 update, which is also when the three label
helpers left the check-authoring surface (they had no external caller left, and the
epoch moved with them, ADR-0051).

:func:`resolve_text` is the layering: the configured text when present, the type's
declared default otherwise, and a configured text may **extend** the default rather
than replace it by writing ``{default}`` into itself — which is what keeps text
inherent to the *type* in one place while a deployment still has the last word,
especially where one type runs several times (one check per team) and would otherwise
carry the same paragraphs in every instance's file. :func:`expand_tokens` lets that
text reuse a value the type declared (an ``org``, a severity legend) via ``{token}``
placeholders — a plain :func:`str.replace`, never ``str.format``, so backticks, braces
and other Markdown in the text stay intact.
"""
from __future__ import annotations

from typing import Any

from little_sister import values
from little_sister.errors import CheckError


def parse_subnodes(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Parse a check config's optional ``subnodes:`` map — ``name -> {title, about}``
    — into ``{name: {"title": …, "about": …}}``. A missing block is ``{}``; a
    malformed one raises :class:`CheckError`, so a typo fails the load loudly.

    **The library is the caller**, like :func:`parse_show_when_quiet` beside it:
    ``Check._parse_common`` runs this for every type and ``Check.__init__``
    resolves what it returns over the type's declared defaults. A check that
    called it would be reading a block already read on its behalf, and would
    resolve a second, different answer for the same names."""
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, show_when_quiet}")
    parsed: dict[str, dict[str, str]] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with "
                f"'title' / 'about' / 'show_when_quiet'")
        parsed[str(name)] = {"title": values.text(meta, "title"),
                             "about": values.text(meta, "about")}
    return parsed


def parse_show_when_quiet(config: dict[str, Any]) -> dict[str, bool]:
    """Parse the ``show_when_quiet`` key out of the same ``subnodes:`` block
    :func:`parse_subnodes` reads — ``{name: True/False}``, and **only for the
    names that state it** (ADR-0063).

    **The library is the caller**, not the check: ``Check._parse_common`` runs
    this for every type and the engine applies the map per child name when a
    result is stored, over the shipped default the child result carries. That is
    deliberate — the key in a deployment's file is the *deployment's* statement,
    and a statement a deployment could only make through a check release would
    put the type in the deployment's lane. (The labels beside it were check-read
    at first, on the argument that layering them needs the type's own default
    text — which held only while that text was code a check applied. They joined
    this reader's side the moment it became a declaration: ADR-0025.) It is
    therefore **not** on the ``little_sister.checks`` facade — and since that
    record, neither is any other name here.

    A **second reader over one block**, rather than a third key in
    :func:`parse_subnodes`'s ``{title, about}`` mapping, and deliberately so. That
    mapping's values are strings, and everything downstream treats them as such —
    layering them through :func:`resolve_text`, scanning them for a ``{token}``. A
    boolean sitting among them would be a string everywhere but at the one call
    site that knew.

    Absence is the tri-state's third value and is carried by **absence from the
    result**: a name this returns nothing for said nothing, so the engine falls
    back to the child result's value — the type's shipped default — and a
    ``nodes.yaml`` declaration, seeded before the first tick, beats both. A
    present ``false`` is a statement and is returned as one. A non-boolean raises
    :class:`CheckError` — ``bool("false")`` is ``True``, so a quoted YAML boolean
    would switch the node on while the config says off.
    """
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, show_when_quiet}")
    declared: dict[str, bool] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with "
                f"'title' / 'about' / 'show_when_quiet'")
        if meta.get("show_when_quiet") is None:
            continue
        declared[str(name)] = values.strict_flag(
            meta, "show_when_quiet", where=f"subnodes.{name}")
    return declared


def resolve_text(configured: str, default: str,
                 tokens: dict[str, str] | None = None) -> str:
    """One label's final text: the type's declared ``default``, what the
    deployment's ``subnodes:`` block says, or both. ``Check.__init__`` is the
    caller — once per name and field, at construction, which is what pins a
    ``{token}`` to a construction-time fact.

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
