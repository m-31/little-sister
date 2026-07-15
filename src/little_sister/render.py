"""Server-side Markdown rendering for node text (ADR-0018).

A small, safe-by-default renderer on markdown-it-py: raw HTML is **escaped**
(``html=False``), link schemes are validated (``javascript:`` / ``vbscript:`` /
``file:`` / unsafe ``data:`` are dropped),
  **images are currently enabled**,
  and links get
``rel="noopener noreferrer"``. Exposed to templates via the ``markdown`` (block) and
``markdown_inline`` (one-line) Jinja filters.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markupsafe import Markup


def _harden_links(self: RendererHTML, tokens: Sequence[Token], idx: int,
                  options: Any, env: Any) -> str:
    """Render-rule override: add ``rel="noopener noreferrer"`` to every link."""
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


def _build() -> MarkdownIt:
    # CommonMark rules, but raw HTML escaped (html=False) — the input includes
    # untrusted captured output (ADR-0018). links validated by default.
    md = MarkdownIt("commonmark", {"html": False})
    # md.disable("image") # We allow currently images.
    md.add_render_rule("link_open", _harden_links)
    return md


_MD = _build()


def render_markdown(text: str) -> Markup:
    """Render a Markdown **block** (paragraphs, lists, code, links) to safe HTML."""
    return Markup(_MD.render(text))


def render_markdown_inline(text: str) -> Markup:
    """Render Markdown **inline** — one line, no wrapping ``<p>`` — to safe HTML."""
    return Markup(_MD.renderInline(text))
