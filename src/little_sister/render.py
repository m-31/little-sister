"""Server-side Markdown rendering for node text (ADR-0018).

A small, safe-by-default renderer on markdown-it-py: raw HTML is **escaped**
(``html=False``), link schemes are validated (``javascript:`` / ``vbscript:`` /
``file:`` / unsafe ``data:`` are dropped),
  fully qualified bare ``http://`` / ``https://`` URLs are linked,
  **images are currently enabled**,
  and links **open in a new tab**
(``target="_blank"``) with ``rel="noopener noreferrer"``. Exposed to templates via the
``markdown`` (block) and ``markdown_inline`` (one-line) Jinja filters.
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
    """Render-rule override: open every link in a new tab (``target="_blank"``)
    with ``rel="noopener noreferrer"`` — so following a link never navigates the
    monitoring page away."""
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


def _build() -> MarkdownIt:
    # CommonMark rules, but raw HTML escaped (html=False) — the input includes
    # untrusted captured output (ADR-0018). Links are validated by default.
    md = MarkdownIt("commonmark", {"html": False, "linkify": True})
    md.enable("linkify")
    if md.linkify is None:  # pragma: no cover - declared runtime dependency
        raise RuntimeError("Markdown linkification requires linkify-it-py")
    # Turn only explicit web URLs into links. Bare domains and email addresses are
    # ordinary prose until an author deliberately gives them a scheme, and ftp /
    # protocol-relative / mailto text does not quietly acquire a click target.
    md.linkify.set({"fuzzy_link": False, "fuzzy_email": False})
    md.linkify.add("ftp:", None)
    md.linkify.add("//", None)
    md.linkify.add("mailto:", None)
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
