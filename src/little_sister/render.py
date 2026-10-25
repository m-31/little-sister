"""Server-side Markdown rendering for node text (ADR-0018).

**One** small, safe-by-default renderer on markdown-it-py, for every text the page shows
— a node's about, description, title and handbook, a line, a maintenance note, what a
check ran with and what its run found (ADR-0018 decision 14) — so that whoever writes
one never asks where it will stand: raw HTML is **escaped** (``html=False``), link
schemes are validated (``javascript:`` / ``vbscript:`` / ``file:`` / unsafe ``data:``
are dropped), fully qualified bare ``http://`` / ``https://`` URLs are linked, GitHub's
tables and strikethrough are drawn, **images are currently enabled**, and links **open
in a new tab** (``target="_blank"``) with ``rel="noopener noreferrer"`` — but for one to
a section of the page itself, ``#sign-in``, which stays in it. Exposed to templates via
the ``markdown`` (block) and ``markdown_inline`` (one line, a title's) Jinja filters,
and to the inspection card's map by :func:`first_block`.

**A status a text names is drawn as its sign** (ADR-0133 decision 5): ``{error}`` and
the other four, in either case, as the status's cue and its word on the status's own
tint (:func:`sign`). In code, or escaped, it stays as written, and ``plain()`` escapes
one a check folds in from what it captured.

**A text links its own node's handbook by a short form** (ADR-0133 decision 4):
``handbook`` for its top and ``handbook#<section>`` for a section. The renderer is
handed the address of the handbook of the node the text belongs to and leads such a
link there, in the rule that sets every link's target (:func:`_harden_links`); on the
handbook's own page it is a section of the page itself, and in a text that belongs to
no node it leads nowhere.

**Where a text leaves the instance** :func:`write_out` writes each placeholder the
renderer draws in it out in the words a document gives a status, and each link it leads
into a handbook out to the handbook's full address: the same parse and the same rules,
block or inline as the page renders the text, so that what the page shows as written —
in code, escaped — stays as written in both.

**A handbook's headings are anchored as GitHub anchors them** (ADR-0133 decision 3),
rendered with ``anchors=True``, which its page alone passes: ``## Sign in`` is
``id="sign-in"`` (:func:`anchor`), and a second heading of the same words ``-1``, so
that a link GitHub would follow into a section follows into it here — and
:func:`anchors_of` says which sections a handbook has, for the startup record's look at
the links into it.
"""
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections.abc import Callable, Sequence
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_core import StateCore
from markdown_it.rules_inline import StateInline
from markdown_it.rules_inline.link import link as _markdown_it_link
from markdown_it.token import Token
from markupsafe import Markup

from little_sister.codes import StatusCode

#: A status a text names in a placeholder's braces (ADR-0133 decision 5): one of the
#: five status words, in either case — ``{error}``, ``{ERROR}``. ASCII's case alone: a
#: Kelvin sign is no ``k``, and the dotted capital I no ``i``.
_PLACEHOLDER = re.compile(
    r"\{(" + "|".join(code.name.lower() for code in StatusCode) + r")\}",
    re.IGNORECASE | re.ASCII)
#: The key of the parser's environment that says the text is a handbook rendered on
#: its page, whose headings are anchored (ADR-0133 decision 3).
_ANCHORS = "anchors"
#: The key of the parser's environment that holds the address of the handbook of the
#: node the text belongs to, where a link written in the short form leads (ADR-0133
#: decision 4) — or what says it, asked only where a link leads there, since most
#: texts write none — and ``None`` where the text belongs to no node.
_HANDBOOK = "handbook"
#: How a text links its own node's handbook (ADR-0133 decision 4): ``handbook`` for
#: its top, and ``handbook#<section>`` for a section of it.
SHORT_FORM = "handbook"
#: The key of the renderer's environment that says the link being rendered leads
#: nowhere, so that its end is not drawn either (:func:`_close_link`).
_LEADS_NOWHERE = "leads_nowhere"
#: A reference's definition up to its destination, ``[sign in]: handbook#sign-in``:
#: where a link it defines in the short form is written out (:func:`_defined`).
_DEFINED = re.compile(
    r"(?<!\\)\]:[ \t]*\n?[ \t]*(?P<destination><[^<>\n]*>|\S+)")
#: What a written-out destination writes of an address as the URL's own escapes, so
#: that a parenthesis in a node's path neither ends the destination nor reads as a
#: backslash in a ticket that shows the Markdown as it is.
_DESTINATION_ESCAPE = {ord(char): f"%{ord(char):02X}" for char in "()<> "}
#: The address of a node's handbook, or what says it when asked (:data:`_HANDBOOK`).
Handbook = str | Callable[[], str]
#: What an anchor keeps of a heading's words besides its letters, marks and digits:
#: GitHub keeps these and drops every other character, and makes each space a hyphen.
_ANCHOR_KEEPS = frozenset("-_ ")
#: The renderer's line endings: markdown-it reads ``\r\n`` and a lone ``\r`` as ``\n``
#: before anything else, so a position it reports is a position in that text.
_LINE_ENDING = re.compile(r"\r\n?")


def short_form(href: str) -> str | None:
    """The section a link written in the short form leads to (ADR-0133 decision 4) —
    ``""`` for the handbook's top and ``"#sign-in"`` for a section — or ``None``
    where ``href`` is no short form."""
    if href == SHORT_FORM:
        return ""
    if href.startswith(SHORT_FORM + "#"):
        return href[len(SHORT_FORM):]
    return None


def _harden_links(self: RendererHTML, tokens: Sequence[Token], idx: int,
                  options: Any, env: Any) -> str:
    """Render-rule override: open every link in a new tab (``target="_blank"``)
    with ``rel="noopener noreferrer"`` — so following a link never navigates the
    monitoring page away. A link to a section of the page itself, ``#sign-in``,
    navigates nowhere and stays in it: a handbook's contents lead to its anchored
    headings (ADR-0133 decision 3).

    A link written in the short form leads into the handbook of the node the text
    belongs to (decision 4) — ``handbook#sign-in`` to ``/handbook/<path>#sign-in`` —
    and opens a tab of its own, as every other link does; on the handbook's own page
    it is a section of the page itself, and stays in it. In a text that belongs to
    no node it leads nowhere: its words stand, and no link."""
    token = tokens[idx]
    href = str(token.attrGet("href") or "")
    section = short_form(href)
    if section is not None:
        if env.get(_ANCHORS):
            href = section or "#"
        elif (address := env.get(_HANDBOOK)) is not None:
            href = f"{address() if callable(address) else address}{section}"
        else:
            env[_LEADS_NOWHERE] = True
            return ""
        token.attrSet("href", href)
    if href.startswith("#"):
        return self.renderToken(tokens, idx, options, env)
    token.attrSet("target", "_blank")
    token.attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


def _close_link(self: RendererHTML, tokens: Sequence[Token], idx: int,
                options: Any, env: Any) -> str:
    """Render-rule override: a link's end — none where the link leads nowhere
    (:func:`_harden_links`), whose words stand alone. Links do not nest, so the one
    being closed is the one that began last."""
    if env.pop(_LEADS_NOWHERE, False):
        return ""
    return self.renderToken(tokens, idx, options, env)


def _link(state: StateInline, silent: bool) -> bool:
    """markdown-it's own link rule, whose link also says where its destination stands
    in the inline text — ``[what to do](handbook#when-it-fails)`` — which is where
    :func:`write_out` writes a short form out (ADR-0133 decision 4). A reference
    link's destination stands in its definition (:func:`_defined`), and says nothing
    here."""
    start, made = state.pos, len(state.tokens)
    if not _markdown_it_link(state, silent):
        return False
    if not silent:
        opened = next((token for token in state.tokens[made:]
                       if token.type == "link_open"), None)
        span = _destination(state, start)
        if opened is not None and span is not None:
            opened.meta["destination"] = span
    return True


def _destination(state: StateInline, start: int) -> tuple[int, int] | None:
    """Where the destination of the inline link that begins at ``start`` stands in
    the inline text, read as markdown-it's link rule reads it, or ``None`` where the
    link is no inline one."""
    label_end = state.md.helpers.parseLinkLabel(state, start, True)
    if label_end < 0:
        return None
    source, end = state.src, state.posMax
    at = label_end + 1
    if at >= end or source[at] != "(":
        return None
    at += 1
    while at < end and source[at] in " \t\n":
        at += 1
    found = state.md.helpers.parseLinkDestination(source, at, end)
    return (at, found.pos) if found.ok else None


def _status_sign(state: StateInline, silent: bool) -> bool:
    """Inline rule: a status placeholder in a text becomes a sign token.

    It runs where the text rule stops, which ``{`` makes it do, and after the rules
    that consume a code span and an escape — so `` `{error}` `` and ``\\{error}`` stay
    as written. The token keeps where its placeholder stood in the inline source, for
    :func:`write_out`."""
    if state.src[state.pos] != "{":
        return False
    found = _PLACEHOLDER.match(state.src, state.pos, state.posMax)
    if found is None:
        return False
    if not silent:
        token = state.push("status_sign", "", 0)
        token.content = found.group(0)
        token.meta = {"code": StatusCode[found.group(1).upper()],
                      "at": found.start(), "end": found.end()}
    state.pos = found.end()
    return True


def _render_sign(self: RendererHTML, tokens: Sequence[Token], idx: int,
                 options: Any, env: Any) -> str:
    return sign(tokens[idx].meta["code"])


def _image(self: RendererHTML, tokens: Sequence[Token], idx: int,
           options: Any, env: Any) -> str:
    """Render-rule override: an image whose words name a status says the status's
    word in its alternative text, where a sign has no place — which the renderer's
    own alt text, made of its words' text alone, would drop."""
    token = tokens[idx]
    if token.children:
        token.children = [
            Token("text", "", 0, content=child.meta["code"].name.lower())
            if child.type == "status_sign" else child
            for child in token.children]
    return RendererHTML.image(self, tokens, idx, options, env)


def anchor(words: str) -> str:
    """The anchor GitHub gives a heading of these words (ADR-0133 decision 3): in
    lower case, each space a hyphen, and every character but a letter, a mark, a
    digit, a hyphen and an underscore dropped — ``Sign in`` is ``sign-in``, ``C++ &
    Go`` is ``c--go``. Empty where nothing is left."""
    return "".join(
        "-" if char == " " else char for char in words.lower()
        if char in _ANCHOR_KEEPS or unicodedata.category(char)[0] in "LM"
        or unicodedata.category(char) in ("Nd", "Nl"))


def _anchor_headings(state: StateCore) -> None:
    """Core rule: give each heading of a handbook the anchor of its words, as a
    reader sees them — a code span's, a link's and a sign's word among them, an
    image's not — and a heading whose anchor an earlier one took the anchor with
    ``-1``, ``-2`` after it, as GitHub counts them. A heading of no anchor has
    none."""
    if not state.env.get(_ANCHORS):
        return
    taken: dict[str, int] = {}
    tokens = state.tokens
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open":
            continue
        words = anchor(_words(tokens[index + 1].children or []))
        found = words
        while found in taken:
            taken[words] += 1
            found = f"{words}-{taken[words]}"
        taken[found] = 0
        if found:
            token.attrSet("id", found)


def _words(children: Sequence[Token]) -> str:
    """A heading's words as a reader sees them, from its inline tokens."""
    words: list[str] = []
    for child in children:
        if child.type in ("text", "code_inline"):
            words.append(child.content)
        elif child.type == "status_sign":
            words.append(child.meta["code"].name.lower())
        elif child.type in ("softbreak", "hardbreak"):
            words.append("\n")
    return "".join(words)


def names_a_status(token: str) -> bool:
    """Whether ``{token}`` names a status (ADR-0133 decision 5): the name a type's
    label token may not take, since the page draws it as the status's sign."""
    return _PLACEHOLDER.fullmatch("{" + token + "}") is not None


def sign(code: StatusCode) -> str:
    """A status as a node's text names it, drawn (ADR-0133 decision 5): the status's
    cue and its word, the word the page shows it with, on the status's own tint, as a
    coded line paints its own surface (ADR-0028) — so it reads on every theme and on
    whatever card it stands in, and never by its colour alone. The word speaks; the
    cue is decorative.

    The cue refers to the shape the page holds once (``cue_sprite``,
    ``_status_cue.html``), as the wall's cues do: the inspection card's map carries
    the first block of every ``about`` in every refresh, and a whole shape in each
    sign would be most of its weight. Every page that shows a node's text holds the
    sprite."""
    slug = code.name.lower()
    return (f'<span class="ls-sign ls-sign--{slug}">'
            f'<svg class="status-cue status-cue--{slug}" aria-hidden="true">'
            f'<use href="#ls-cue-{slug}"/></svg>{slug}</span>')


def _build() -> MarkdownIt:
    """The renderer: CommonMark with GitHub's tables and strikethrough and the status
    signs (ADR-0018 decisions 13 and 14)."""
    # CommonMark rules, but raw HTML escaped (html=False) — the input includes
    # untrusted captured output (ADR-0018). Links are validated by default.
    # `store_labels`: a reference link says which label it was found by, which is
    # all the writing out of signs asks of it (`_written`)
    md = MarkdownIt("commonmark", {"html": False, "linkify": True,
                                   "store_labels": True})
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
    md.add_render_rule("link_close", _close_link)
    # Its own link rule, whose links say where their destinations stand, for a short
    # form written out where a text leaves the instance (ADR-0133 decision 4).
    md.inline.ruler.at("link", _link)
    md.add_render_rule("image", _image)
    # GitHub's tables and strikethrough, which a runbook's contacts and commands stand
    # in (ADR-0018 decision 14): markdown-it-py's own rules, switched on.
    md.enable(["table", "strikethrough"])
    # A status placeholder (ADR-0133 decision 5). The text rule stops at `{` already;
    # saying so keeps the rule firing if that ever changes.
    md.inline.add_terminator_char("{")
    md.inline.ruler.push("status_sign", _status_sign)
    md.add_render_rule("status_sign", _render_sign)
    # A handbook's headings, anchored on its page (ADR-0133 decision 3): after every
    # rule that makes a heading's words, so that what is anchored is what is shown.
    md.core.ruler.push("anchors", _anchor_headings)
    return md


_MD = _build()


def render_markdown(text: str, *, anchors: bool = False,
                    handbook: Handbook | None = None) -> Markup:
    """Render a Markdown **block** (paragraphs, lists, tables, code, links) to safe
    HTML, for the node whose handbook is at ``handbook`` — where a link written in the
    short form leads, the address or what says it when asked; ``None`` for a text that
    belongs to no node — and with ``anchors``, a handbook on its own page, each
    heading anchored."""
    return Markup(_MD.render(text, {_ANCHORS: anchors, _HANDBOOK: handbook}))


def render_markdown_inline(text: str, *, handbook: Handbook | None = None) -> Markup:
    """Render Markdown **inline** — one line, no wrapping ``<p>`` — to safe HTML: a
    title, which stands in a line of its own, or a text a row sums up. ``handbook`` as
    for :func:`render_markdown`."""
    return Markup(_MD.renderInline(text, {_HANDBOOK: handbook}))


def first_block(text: str, *,
                handbook: Handbook | None = None) -> tuple[Markup, int]:
    """The first top-level block of ``text`` — a paragraph, a list, a code block,
    whatever its Markdown opens with — rendered as :func:`render_markdown` renders
    the whole, and the number of top-level blocks after it.

    What the inspection card says of a node's ``about`` (ADR-0019): its first
    paragraph, and how much more the node's page has, so that a type's documentation
    stays a card and does not become a page. Read off markdown-it's tokens, so a
    block is what the renderer makes one, a list with its items or a fenced block
    with its blank lines, and a link reference defined further down still resolves.
    Text with no block at all is ``("", 0)``. ``handbook`` as for
    :func:`render_markdown`."""
    env: dict[str, Any] = {_HANDBOOK: handbook}
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


def anchors_of(handbook: str) -> frozenset[str]:
    """The anchors a handbook's own page gives its headings (ADR-0133 decision 3):
    the sections a link written ``handbook#<section>`` may lead to."""
    return frozenset(str(token.attrGet("id"))
                     for token in _MD.parse(handbook, {_ANCHORS: True})
                     if token.type == "heading_open" and token.attrGet("id"))


def short_links(text: str, *, inline: bool = False) -> list[str]:
    """Where each link ``text`` writes in the short form leads — ``""`` for the
    handbook's top, ``"#sign-in"`` for a section, as :func:`short_form` says it — in
    the order they stand, the text read as the renderer reads it, a block or
    ``inline``: a link in code or escaped is none (ADR-0133 decision 4)."""
    tokens = _MD.parseInline(text, {}) if inline else _MD.parse(text, {})
    return [section for block in tokens for child in block.children or ()
            if child.type == "link_open"
            and (section := short_form(str(child.attrGet("href") or ""))) is not None]


def write_out(text: str, word: Callable[[StatusCode], str], *, handbook: str = "",
              inline: bool = False) -> str:
    """``text`` as it leaves the instance (ADR-0133 decisions 4 and 5): each status
    placeholder the renderer draws as a sign in it written as ``word(code)``; given
    ``handbook``, the full address of the handbook of the node the text belongs to,
    each link the renderer leads into that handbook — written ``handbook`` or
    ``handbook#<section>``, in the link or in the definition of its reference —
    written out to that address; and everything else as it was. Read as the page
    renders the text: ``inline``, as a title is, or as a block, as every other text
    is.

    It reads the text with the renderer's own parse and rules, so that what the page
    shows as written stays as written here: a placeholder or a link in code or
    escaped, a placeholder that is a reference link's label, `[{error}]`, whose
    definition would no longer answer to it, and one in an image's words. Its line
    endings come back as ``\\n`` where it has something to write."""
    # A link stands in a text as `](` or, defined, `]:`: one that writes neither and
    # no placeholder has nothing to write out.
    if (_PLACEHOLDER.search(text) is None
            and not (handbook and ("](" in text or "]:" in text))):
        return text
    source = _LINE_ENDING.sub("\n", text)
    found = _spans_in(source, inline, word, handbook)
    if not found:
        return text
    written: list[str] = []
    done = 0
    for start, end, replacement in found:
        written.extend((source[done:start], replacement))
        done = end
    written.append(source[done:])
    return "".join(written)


#: A stretch of a source :func:`write_out` writes otherwise: where it begins and ends,
#: and what is written in its place.
_Span = tuple[int, int, str]


def _spans_in(source: str, inline: bool, word: Callable[[StatusCode], str],
              handbook: str) -> list[_Span]:
    """Where in ``source`` :func:`write_out` writes something else, and what, in
    order: each placeholder the renderer draws as a sign, and — given ``handbook`` —
    each destination of a link written in the short form.

    markdown-it says where a sign and a link's destination stood in their block's
    inline text, which is the block's lines without what marks them as a list item, a
    quotation or a heading: each of those lines ends the source line it came from
    (:func:`_within`), and the first of them may be a later line than the block's
    first, where a line blank to Python's ``strip`` — a no-break space alone — opened
    the block and markdown-it-py stripped it away (:func:`_begins`). A table's cell is
    a stretch of its row's line (:func:`_in_cell`), and a reference's definition says
    which lines it stands on (:func:`_defined`). A block whose lines are not found in
    the source is left as written rather than written in the wrong place, and so is a
    stretch that is not where its line puts it. The parser reads a NUL as U+FFFD, a
    character for a character, so its text is compared with the source read the same
    way."""
    seen = source.replace("\0", "\ufffd")
    lines = seen.split("\n")
    line_starts = [0]
    for line in lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)
    env: dict[str, Any] = {}
    tokens = _MD.parseInline(source, env) if inline else _MD.parse(source, env)
    found: list[_Span] = []
    rows: dict[int, int] = {}
    for index, block in enumerate(tokens):
        if block.type != "inline" or block.map is None:
            continue
        if index and tokens[index - 1].type in ("th_open", "td_open"):
            found.extend(_in_cell(block, seen, lines, line_starts, rows, word,
                                  handbook))
            continue
        if not block.children:
            continue
        stretches = _written(block.children, block.content, word, handbook)
        if not stretches:
            continue
        inline_lines = block.content.split("\n")
        begins = _begins(inline_lines, lines, line_starts, block.map[0], block.map[1])
        if begins is None:
            continue
        inline_starts = [0]
        for inline_line in inline_lines[:-1]:
            inline_starts.append(inline_starts[-1] + len(inline_line) + 1)
        for at, end, written, replacement in stretches:
            number = bisect_right(inline_starts, at) - 1
            start = begins[number] + at - inline_starts[number]
            if seen[start:start + end - at] == written:
                found.append((start, start + end - at, replacement))
    if handbook:
        found.extend(_defined(env, seen, line_starts, handbook))
    return sorted(found)


def _in_cell(cell: Token, seen: str, lines: list[str], line_starts: list[int],
             rows: dict[int, int], word: Callable[[StatusCode], str],
             handbook: str) -> list[_Span]:
    """What :func:`write_out` writes in a table's cell, where it stands in the source:
    a cell's text is a stretch of its row's line, found after the cell before it —
    ``rows`` says where each row's next cell is looked for — and with each ``|`` in it
    written ``\\|``, as the source escapes a pipe that does not end the cell. A cell
    that is not found leaves the rest of its row as written, as a block that is not
    found does."""
    number = cell.map[0] if cell.map else len(lines)
    after = rows.get(number, line_starts[number] if number < len(lines) else -1)
    if after < 0:
        return []
    spelled = cell.content.replace("|", "\\|")
    at = seen.find(spelled, after, line_starts[number] + len(lines[number]))
    if at < 0:
        rows[number] = -1
        return []
    rows[number] = at + len(spelled)
    found: list[_Span] = []
    for offset, end, written, replacement in _written(cell.children or [],
                                                      cell.content, word, handbook):
        start = at + offset + cell.content.count("|", 0, offset)
        stop = start + end - offset
        if seen[start:stop] == written:
            found.append((start, stop, replacement))
    return found


def _written(children: Sequence[Token], text: str, word: Callable[[StatusCode], str],
             handbook: str) -> list[tuple[int, int, str, str]]:
    """What of a block's inline ``text`` is written out, where it stands in it, as it
    stands there and as it is written: each sign, as ``word`` writes its status — but
    one in a reference link's label that names a status, `[{error}]`, `[{error}][]`,
    whose definition keeps its label as written — and, given ``handbook``, the
    destination of each inline link written in the short form, written out to that
    address. A sign in an image's words is a child of the image, and stays as written
    too."""
    written: list[tuple[int, int, str, str]] = []
    label = ""
    for child in children:
        if child.type == "link_open":
            label = str(child.meta.get("label") or "")
            href = str(child.attrGet("href") or "")
            span = child.meta.get("destination")
            if handbook and span is not None and short_form(href) is not None:
                at, end = span
                written.append((at, end, text[at:end],
                                _addressed(text[at:end], href, handbook)))
        elif child.type == "link_close":
            label = ""
        elif child.type == "status_sign" and not _PLACEHOLDER.search(label):
            written.append((child.meta["at"], child.meta["end"], child.content,
                            word(child.meta["code"])))
    return written


def _defined(env: dict[str, Any], seen: str, line_starts: list[int],
             handbook: str) -> list[_Span]:
    """The destination of each reference's definition written in the short form,
    ``[sign in]: handbook#sign-in``, where it stands in the source and written out to
    ``handbook``: markdown-it says which lines a definition stands on, and the
    destination is the first after its label. One that is not found there stays as
    written."""
    found: list[_Span] = []
    for reference in (env.get("references") or {}).values():
        href = str(reference.get("href") or "")
        lines = reference.get("map")
        if short_form(href) is None or not lines:
            continue
        first, after = lines
        start = line_starts[first] if first < len(line_starts) else len(seen)
        stop = line_starts[after] if after < len(line_starts) else len(seen)
        defined = _DEFINED.search(seen, start, stop)
        if defined is not None:
            destination = defined.group("destination")
            found.append((defined.start("destination"), defined.end("destination"),
                          _addressed(destination, href, handbook)))
    return found


def _addressed(written: str, href: str, address: str) -> str:
    """A destination written in the short form, written out to ``address``: the
    section as its author wrote it, in angle brackets where they did — or, where
    the destination spells the short form some other way, an entity for a letter,
    the section as the link leads to it."""
    bracketed = written.startswith("<") and written.endswith(">")
    inner = written[1:-1] if bracketed else written
    escaped = address.translate(_DESTINATION_ESCAPE)
    if not inner.startswith(SHORT_FORM):
        return escaped + (short_form(href) or "")
    out = escaped + inner[len(SHORT_FORM):]
    return f"<{out}>" if bracketed else out


def _begins(inline_lines: list[str], lines: list[str], line_starts: list[int],
            first: int, after: int) -> list[int] | None:
    """Where each line of a block's inline text begins in the source, the block being
    the source's lines ``first`` up to ``after``; ``None`` where they are not found.
    The text begins on the first of those lines from which every one of its lines is
    found, a line before it being one markdown-it-py's ``strip`` took off its front."""
    for top in range(first, max(first + 1, after)):
        begins: list[int] = []
        for number, inline_line in enumerate(inline_lines):
            index = top + number
            within = _within(lines[index], inline_line) if index < len(lines) else None
            if within is None:
                break
            begins.append(line_starts[index] + within)
        else:
            return begins
    return None


def _within(line: str, inline_line: str) -> int | None:
    """Where ``inline_line`` — a line of a block's inline text — begins in the source
    line it came from, or ``None``: an offset that puts each of its characters past
    its leading blanks where that character stands in the source, which is all a
    placeholder needs."""
    words = inline_line.lstrip()
    for candidate in (line, line.rstrip()):
        if candidate.endswith(inline_line):
            return len(candidate) - len(inline_line)
        if words and candidate.endswith(words):
            # blanks the parser counted a tab of the indentation out in
            return len(candidate) - len(inline_line)
    found = line.find(inline_line)
    return None if found < 0 else found
