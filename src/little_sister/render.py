"""Server-side Markdown rendering for node text (ADR-0018).

A small, safe-by-default renderer on markdown-it-py: raw HTML is **escaped**
(``html=False``), link schemes are validated (``javascript:`` / ``vbscript:`` /
``file:`` / unsafe ``data:`` are dropped),
  fully qualified bare ``http://`` / ``https://`` URLs are linked,
  **images are currently enabled**,
  and links **open in a new tab**
(``target="_blank"``) with ``rel="noopener noreferrer"``. Exposed to templates via the
``markdown`` (block) and ``markdown_inline`` (one-line) Jinja filters, and to the
inspection card's map by :func:`first_block`.
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


def first_block(text: str) -> tuple[Markup, int]:
    """The first top-level block of ``text`` — a paragraph, a list, a code block,
    whatever its Markdown opens with — rendered as :func:`render_markdown` renders
    the whole, and the number of top-level blocks after it.

    What the inspection card says of a node's ``about`` (ADR-0019): its first
    paragraph, and how much more the node's page has, so that a type's documentation
    stays a card and does not become a page. Read off markdown-it's tokens, so a
    block is what the renderer makes one, a list with its items or a fenced block
    with its blank lines, and a link reference defined further down still resolves.
    Text with no block at all is ``("", 0)``."""
    env: dict[str, Any] = {}
    blocks: list[list[Token]] = []
    depth = 0
    for token in _MD.parse(text, env):
        if depth == 0:
            blocks.append([])
        blocks[-1].append(token)
        depth += token.nesting
    if not blocks:
        return Markup(""), 0
    return Markup(_MD.renderer.render(blocks[0], _MD.options, env)), len(blocks) - 1
