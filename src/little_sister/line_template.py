"""A line as a template over its record (ADR-0126).

A check type writes the sentence of a line that carries a record as a **form**: a
template its grading names when it asks the library for the line
(:meth:`~little_sister.checks.Check.line`), rendered there and once, into the line's
``text``, over the reading's **record** and the **words** the grading hands over with
it. A word is what the type adds from its configuration, from the clock or as its own
wording — a link wrapped in a configured template, a label after a rule shortened a
name, an age, a rule's own sentence — and it lives for the rendering alone: it is
never stored, published or weighed (decision 2). A deployment re-words a form in the
check's own ``display:`` block, over what the type declares (decision 5). This module
is the notation, the rendering and the declarations; :class:`~little_sister.checks.
Check` holds them, resolved once, when the check is built.

**The notation** (decision 5):

* ``{completed.run_number}`` — a field of the record, by the dotted name the node's
  record list spells it with;
* ``{line.why}`` — a word, under a namespace of its own, so that no field can stand
  for a word nor a word for a field;
* ``{line.default}`` — the layer beneath: under a deployment's template, the type's
  default text for the same form, rendered over the same record and words;
* ``{? …}`` — a **segment**, shown when every value it prints is there, and
  ``{?name: …}``, shown when ``name`` is there as well, which it need not print, so
  that a flag works. Segments nest. What follows the mark is the segment's own, its
  spaces too: ``CI{? on {branch}}`` reads ``CI`` where there is no branch;
* ``{{`` writes ``{``, and ``}}`` writes ``}`` outside a segment — inside one a ``}``
  ends it, so that two segments ending together read ``}}``;
* everything else is Markdown, in which a brace means nothing.

A value is **absent** where it is null, missing, empty or false (decision 3); zero is
a value. That is the one construct beyond substitution: no else, no not, no
comparison, no loop and no filter.

**What prints.** A value absent outside every segment prints :data:`ABSENT`, the
library's spelling of *none*, visible and never an error that costs the run. A time
under ``at``, ``started`` or ``ended`` — the names the seam reads as an instant
(:data:`~little_sister.reasons.RECORD_TIMESTAMP_KEYS`) — is written in the configured
``timezone`` and ``time_format`` through :func:`~little_sister.spans.local_time`, the
one function every time a page shows goes through. Text is written as it reads, and
any other value as its JSON, as the node's record list shows it. Every value is
escaped as :func:`~little_sister.reasons.plain` escapes one, so that a name never
turns into formatting or a link.

**A link** is Markdown's own (decision 4): ``[words]({completed.url})`` or
``[words]({line.link})``, its target one value — a URL the record holds, or a word,
one the type builds out of what the record holds whole. A target that is absent, or
is not an http(s) URL, leaves the link's words as plain text, so that a missing link
never hides what it labels. A target is written as Markdown reads a URL: a backslash, a
parenthesis without its partner and an ``&`` that would begin a character reference
are escaped, and nothing else, so that an address reads in a line as it reads
anywhere else.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from little_sister.reasons import RECORD_TIMESTAMP_KEYS, plain
from little_sister.spans import local_time

#: What a value absent outside every segment prints: the library's spelling of
#: *none*, as :func:`~little_sister.spans.format_span` writes an unmeasured span.
ABSENT = "—"

#: The namespace a word is named in, and the one name in it that is no word.
WORDS = "line"
DEFAULT = "default"
_WORD = f"{WORDS}."
_BENEATH = f"{WORDS}.{DEFAULT}"

#: One part of a name: a field's key, a word, a part of a form's name.
_PART = r"[A-Za-z0-9_][A-Za-z0-9_-]*"
_NAME = rf"{_PART}(?:\.{_PART})*"
_PART_ALONE = re.compile(_PART)
_NAME_ALONE = re.compile(_NAME)
_VALUE = re.compile(rf"\{{({_NAME})\}}")
_FLAG = re.compile(rf"({_NAME}):")
_TARGET = re.compile(rf"\(\{{({_NAME})\}}\)")

#: An ``&`` that Markdown would read as the start of a character reference.
_REFERENCE = re.compile(
    r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{0,31});")

#: How deep Markdown nests the parentheses of a link's target before it stops
#: reading one (CommonMark leaves the bound to the parser; markdown-it's is 32).
_NESTED = 32

#: What a declaration of a form, and one of a word or a field, holds.
_FORM_KEYS = frozenset({"sentence", "text"})
_DECLARED_KEYS = frozenset({"sentence", "example"})


class TemplateError(ValueError):
    """A template the notation cannot read, a name its type does not declare, or a
    declaration of another shape. The message names the place and, inside a
    template, the character; :class:`~little_sister.checks.Check` refuses its
    construction with it, which stops the start naming the file (ADR-0051)."""


# --- what a template is read into -------------------------------------------------

@dataclass(frozen=True)
class _Text:
    """Markdown, as written."""
    text: str


@dataclass(frozen=True)
class _Value:
    """A field's dotted name, or ``line.`` and a word."""
    name: str


@dataclass(frozen=True)
class _Beneath:
    """``{line.default}``: the layer beneath."""


@dataclass(frozen=True)
class _Segment:
    """What is shown only where the values it names are there: ``when``, which it
    need not print, and every value its body prints."""
    when: str | None
    body: tuple[_Node, ...]


@dataclass(frozen=True)
class _Link:
    """Markdown's link, whose target is one value."""
    words: tuple[_Node, ...]
    target: str


_Node = _Text | _Value | _Beneath | _Segment | _Link


def _named(nodes: tuple[_Node, ...]) -> Iterator[str]:
    """Every name ``nodes`` holds, wherever it stands: the values, the flags, the
    targets, and ``line.default``."""
    for node in nodes:
        if isinstance(node, _Value):
            yield node.name
        elif isinstance(node, _Beneath):
            yield _BENEATH
        elif isinstance(node, _Segment):
            if node.when is not None:
                yield node.when
            yield from _named(node.body)
        elif isinstance(node, _Link):
            yield from _named(node.words)
            yield node.target


def _printed(nodes: tuple[_Node, ...]) -> Iterator[str]:
    """The names a segment's body prints itself — its values, a link's words among
    them — and never those of a segment inside it, which decides for itself, nor a
    link's target, whose absence leaves the words standing."""
    for node in nodes:
        if isinstance(node, _Value):
            yield node.name
        elif isinstance(node, _Link):
            yield from _printed(node.words)


@dataclass(frozen=True)
class Template:
    """A template as it was read: the text it was read from, and what that names."""

    source: str
    nodes: tuple[_Node, ...] = field(repr=False, compare=False)

    @property
    def fields(self) -> frozenset[str]:
        """The record's fields it names, by their dotted names."""
        return frozenset(name for name in _named(self.nodes)
                         if not name.startswith(_WORD))

    @property
    def words(self) -> frozenset[str]:
        """The words it names, without their namespace."""
        return frozenset(name[len(_WORD):] for name in _named(self.nodes)
                         if name.startswith(_WORD) and name != _BENEATH)

    @property
    def defers(self) -> bool:
        """Whether it names the layer beneath it, ``{line.default}``."""
        return _BENEATH in set(_named(self.nodes))


# --- reading one ------------------------------------------------------------------

_BRACE = "a field is named by its dotted name, as {completed.run_number}, a word as " \
         "{line.why}, and {{ writes a brace"


def _reference(name: str, at: int, source: str) -> _Value | _Beneath:
    """The value ``name`` stands for, read at character ``at`` (from zero) of
    ``source``: ``line.default``, a word, or a field."""
    if name == WORDS or (name.startswith(_WORD) and "." in name[len(_WORD):]):
        raise TemplateError(
            f"{_shown(source, at)} at character {at + 1} names no field and no word: "
            f"{_BRACE}")
    if name == _BENEATH:
        return _Beneath()
    return _Value(name)


def _shown(source: str, at: int) -> str:
    """The reference that starts at ``at``, as a refusal quotes it: up to its
    closing brace, or a few characters where it has none."""
    closes = source.find("}", at, at + 41)
    return repr(source[at:closes + 1] if closes != -1 else source[at:at + 20])


class _Reader:
    """One template, read once from its start."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.at = 0

    def sequence(self, *, segment: bool, link: bool) -> tuple[_Node, ...]:
        """What stands up to the end — or, inside a segment, up to the ``}`` that
        ends it, and inside a link's words up to the ``]`` that ends them, either
        left for the caller to read."""
        source = self.source
        nodes: list[_Node] = []
        text: list[str] = []

        def written() -> None:
            if text:
                nodes.append(_Text("".join(text)))
                text.clear()

        while self.at < len(source):
            char = source[self.at]
            if char == "{":
                if source.startswith("{{", self.at):
                    text.append("{")
                    self.at += 2
                    continue
                written()
                nodes.append(self._segment() if source.startswith("{?", self.at)
                             else self._value())
                continue
            if char == "}":
                if segment:
                    break
                if source.startswith("}}", self.at):
                    text.append("}")
                    self.at += 2
                    continue
                raise TemplateError(
                    f"the }} at character {self.at + 1} closes nothing: a segment "
                    f"ends at its }}, and }}}} writes a brace")
            if char == "]" and link:
                break
            if char == "[":
                found = self._link(segment)
                if found is not None:
                    written()
                    nodes.append(found)
                    continue
            text.append(char)
            self.at += 1
        written()
        return tuple(nodes)

    def _value(self) -> _Value | _Beneath:
        at = self.at
        found = _VALUE.match(self.source, at)
        if found is None:
            raise TemplateError(
                f"{_shown(self.source, at)} at character {at + 1} names no field and "
                f"no word: {_BRACE}")
        self.at = found.end()
        return _reference(found.group(1), at, self.source)

    def _segment(self) -> _Segment:
        at = self.at
        self.at += 2
        when: str | None = None
        flag = _FLAG.match(self.source, self.at)
        if flag is not None:
            if isinstance(_reference(flag.group(1), at, self.source), _Beneath):
                raise TemplateError(
                    f"the segment at character {at + 1} asks for {{{_BENEATH}}}, "
                    f"which is the text of the layer beneath and is always there; a "
                    f"segment asks for a field or a word")
            when = flag.group(1)
            self.at = flag.end()
        body = self.sequence(segment=True, link=False)
        if self.at >= len(self.source):
            raise TemplateError(
                f"the segment at character {at + 1} never ends: a segment ends at "
                f"its }}")
        self.at += 1
        return _Segment(when, body)

    def _link(self, segment: bool) -> _Link | None:
        """The link that starts here, if its target is a value — and ``None``, back
        where it started, for brackets that make no such link: Markdown's own, a
        link written out, or text."""
        at = self.at
        self.at += 1
        try:
            words = self.sequence(segment=segment, link=True)
        except TemplateError:
            # Read again as text, where the same refusal comes back at its place.
            self.at = at
            return None
        source = self.source
        if not source.startswith("](", self.at):
            self.at = at
            return None
        opens = self.at + 1
        target = _TARGET.match(source, opens)
        if target is not None:
            if isinstance(_reference(target.group(1), opens + 1, source), _Beneath):
                raise TemplateError(
                    f"the link's target at character {opens + 1} is {{{_BENEATH}}}, "
                    f"the text of the layer beneath; a target is a URL the record "
                    f"holds or a word")
            self.at = target.end()
            return _Link(words, target.group(1))
        closes = source.find(")", opens)
        written = source[opens + 1:closes if closes != -1 else len(source)]
        if "{" in written.replace("{{", ""):
            raise TemplateError(
                f"the link's target at character {opens + 1} is one value, a URL the "
                f"record holds or a word — [words]({{completed.url}}), "
                f"[words]({{line.link}}) — and never text around one")
        self.at = at
        return None


def parse(source: str) -> Template:
    """``source`` as a template, or :class:`TemplateError` naming the character the
    notation could not read."""
    reader = _Reader(source)
    return Template(source, reader.sequence(segment=False, link=False))


# --- rendering one ----------------------------------------------------------------

def absent(value: object) -> bool:
    """Whether ``value`` counts as not there: null, missing, empty or false. Zero is
    a value (decision 3)."""
    if value is None or value is False:
        return True
    return isinstance(value, str | Mapping | list | tuple) and not value


def _local(value: object) -> str | None:
    """A value under a timed name in the configured zone and format, where it is an
    ISO-8601 string carrying an offset that zone can hold — the form the seam stores
    every time in — and ``None`` for anything written as it is held."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    try:
        return local_time(moment)
    except (OverflowError, ValueError):
        return None


def _target(value: object) -> str | None:
    """``value`` as a link's target, or ``None`` where it is none: absent, not text,
    holding a space or a control character, or not an http(s) URL with a host."""
    if not isinstance(value, str) or not value:
        return None
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return _destination(value)


def _destination(url: str) -> str:
    """``url`` as Markdown reads it as a link's target: each backslash escaped, each
    parenthesis without its partner — or all of them, nested deeper than Markdown
    reads — and each ``&`` that would begin a character reference. Nothing else is
    touched, so a URL that needs none of it is written as it reads."""
    opened: list[int] = []
    partnered: set[int] = set()
    for index, char in enumerate(url):
        if char == "(":
            opened.append(index)
        elif char == ")" and opened:
            partnered.update((opened.pop(), index))
    depth = deepest = 0
    for index in sorted(partnered):
        depth += 1 if url[index] == "(" else -1
        deepest = max(deepest, depth)
    if deepest > _NESTED:
        partnered.clear()
    written: list[str] = []
    for index, char in enumerate(url):
        if char == "\\" or (char in "()" and index not in partnered) or (
                char == "&" and _REFERENCE.match(url, index)):
            written.append("\\")
        written.append(char)
    return "".join(written)


class _Rendering:
    """One template rendered over one record and the words handed over with it."""

    def __init__(self, record: Mapping[str, Any], words: Mapping[str, object],
                 beneath: Template | None) -> None:
        self.record = record
        self.words = words
        self.beneath = beneath

    def value(self, name: str) -> object:
        """What ``name`` stands for: a word, or the field of that dotted name —
        ``None`` where the record holds no such field."""
        if name.startswith(_WORD):
            return self.words.get(name[len(_WORD):])
        return field_of(self.record, name)

    def nodes(self, nodes: tuple[_Node, ...]) -> str:
        return "".join(self.node(node) for node in nodes)

    def node(self, node: _Node) -> str:
        if isinstance(node, _Text):
            return node.text
        if isinstance(node, _Value):
            value = self.value(node.name)
            return ABSENT if absent(value) else _written(node.name, value)
        if isinstance(node, _Beneath):
            if self.beneath is None:
                return ABSENT
            return _Rendering(self.record, self.words, None).nodes(self.beneath.nodes)
        if isinstance(node, _Segment):
            if node.when is not None and absent(self.value(node.when)):
                return ""
            if any(absent(self.value(name)) for name in _printed(node.body)):
                return ""
            return self.nodes(node.body)
        words = self.nodes(node.words)
        target = _target(self.value(node.target))
        return words if target is None else f"[{words}]({target})"


def field_of(record: Mapping[str, Any], name: str) -> object:
    """The field of ``record`` that the dotted ``name`` names, as a template reads it
    — ``None`` where the record holds no such field. The one reading of a dotted name,
    which a type's ``occurrence=`` is read by too (ADR-0142)."""
    found: object = record
    for key in name.split("."):
        if not isinstance(found, Mapping) or key not in found:
            return None
        found = found[key]
    return found


def _written(name: str, value: object) -> str:
    """A value that is there, as a line writes it: a time under a timed name in the
    configured zone, text as it reads, anything else as its JSON — escaped."""
    if not name.startswith(_WORD) and name.rpartition(".")[2] in RECORD_TIMESTAMP_KEYS:
        local = _local(value)
        if local is not None:
            return plain(local)
    if isinstance(value, str):
        return plain(value)
    return plain(json.dumps(value, default=str))


def render(template: Template, record: Mapping[str, Any],
           words: Mapping[str, object], *, beneath: Template | None = None) -> str:
    """``template`` over ``record`` and ``words``, as Markdown — ``beneath`` the
    layer ``{line.default}`` names. Total: whatever the values are, it answers a
    text and raises nothing."""
    return _Rendering(record, words, beneath).nodes(template.nodes)


# --- what a type declares, and what a deployment re-words -------------------------

@dataclass(frozen=True)
class Form:
    """One sentence a type's grading may choose to say (decision 3): its full name,
    one sentence saying when the grading says it, and its default text."""

    name: str
    sentence: str
    text: str
    template: Template = field(repr=False, compare=False)


@dataclass(frozen=True)
class Declared:
    """A word, or a field of the record, that a template may name: its name, one
    sentence, and an example — written as the page writes a value, so that what a
    deployment reads on ``/system/installed`` is what a line would print."""

    name: str
    sentence: str
    example: str


@dataclass(frozen=True)
class Declarations:
    """What a type declares of its lines (decision 5): the forms its grading names,
    and the words and the fields a template may name — each in the type's order."""

    forms: tuple[Form, ...] = ()
    words: tuple[Declared, ...] = ()
    fields: tuple[Declared, ...] = ()


@dataclass(frozen=True)
class Wording:
    """What one form says on one check: the template it is rendered from — the
    deployment's, where its ``display:`` block re-words the form, and the type's
    default otherwise — and the layer beneath, which ``{line.default}`` names: the
    type's default under the deployment's, and nothing under the default itself."""

    template: Template
    beneath: Template | None = None


def _listed(names: Iterable[str]) -> str:
    """Names as a refusal lists them — or *none*."""
    return ", ".join(sorted(names)) or "none"


def _block(value: object, where: str, shape: str) -> Mapping[object, object]:
    """A declaration's mapping, or a refusal saying what it maps: absent is empty."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TemplateError(f"{where} maps {shape}, and is {type(value).__name__}")
    return value


def _entry(value: object, where: str, keys: frozenset[str]) -> Mapping[str, object]:
    """One declaration's entry: a mapping of exactly ``keys``, each one there."""
    wanted = " and ".join(f"'{key}'" for key in sorted(keys))
    if not isinstance(value, Mapping):
        raise TemplateError(f"{where} must be a mapping of {wanted}, not {value!r}")
    taken = {str(key) for key in value}
    if taken != keys:
        raise TemplateError(f"{where} takes {wanted}, and holds {_listed(taken)}")
    return {str(key): item for key, item in value.items()}


def _sentence(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TemplateError(f"{where}.sentence must be one sentence, not {value!r}")
    return value


def _example(value: object, where: str) -> str:
    """An example as the page writes a value: text as it reads, anything else as
    its JSON."""
    if value is None or value == "":
        raise TemplateError(f"{where}.example must be an example of what it holds, "
                            f"not {value!r}")
    return value if isinstance(value, str) else json.dumps(value, default=str)


def _read(text: object, where: str) -> Template:
    """A form's text as a template, or the refusal naming ``where`` it stands."""
    if not isinstance(text, str) or not text.strip():
        raise TemplateError(f"{where} must be a template, a line's text, not {text!r}")
    try:
        return parse(text)
    except TemplateError as error:
        raise TemplateError(f"{where}: {error}") from None


def _declared(value: object, where: str, *, word: bool) -> tuple[Declared, ...]:
    """The words, or the fields, a type declares: each a name of the notation's
    shape — a word one name, never ``default``, and a field a dotted one, never in
    the words' namespace — one sentence and an example."""
    declared: list[Declared] = []
    for name, entry in _block(value, where, "a name to its sentence and an "
                                            "example").items():
        if word:
            fits = isinstance(name, str) and bool(_PART_ALONE.fullmatch(name))
            if fits and name == DEFAULT:
                raise TemplateError(
                    f"{where} declares 'default', which is no word: "
                    f"{{{_BENEATH}}} is the text of the layer beneath")
        else:
            fits = isinstance(name, str) and bool(_NAME_ALONE.fullmatch(name))
            if fits and str(name).split(".")[0] == WORDS:
                raise TemplateError(
                    f"{where} declares {name!r}, which a template would read as a "
                    f"word: a field's name never starts with '{WORDS}'")
        if not fits:
            shape = ("one name, as why or link" if word
                     else "a dotted name, as completed.run_number")
            raise TemplateError(f"{where} declares {name!r}, which is not {shape}")
        named = f"{where}.{name}"
        held = _entry(entry, named, _DECLARED_KEYS)
        declared.append(Declared(str(name), _sentence(held["sentence"], named),
                                 _example(held["example"], named)))
    return tuple(declared)


def _names_declared(template: Template, where: str,
                    declarations: Declarations) -> None:
    """Refuse ``template`` where it names a field or a word ``declarations`` does
    not declare — the check startup makes of a deployment's template, and a check
    of the type's own defaults when one is built."""
    fields = frozenset(item.name for item in declarations.fields)
    words = frozenset(item.name for item in declarations.words)
    unknown = sorted(template.fields - fields)
    if unknown:
        raise TemplateError(
            f"{where} names the field {unknown[0]!r}, which this type does not "
            f"declare; it declares {_listed(fields)}")
    unknown = sorted(template.words - words)
    if unknown:
        raise TemplateError(
            f"{where} names the word '{_WORD}{unknown[0]}', which this type does not "
            f"declare; it declares {_listed(_WORD + word for word in words)}")


def declare(forms: object, words: object, fields: object) -> Declarations:
    """A type's three declarations, read: every name of the notation's shape, every
    entry one sentence and its default text or an example, and every default a
    template naming only what the type declares, with nothing beneath it — so that
    a typo in a default fails the type's own tests (decision 5)."""
    declared = Declarations(
        words=_declared(words, "line_words", word=True),
        fields=_declared(fields, "line_fields", word=False))
    read: list[Form] = []
    for name, entry in _block(forms, "line_forms", "a form's name to its sentence "
                                                    "and its default text").items():
        if not isinstance(name, str) or not _NAME_ALONE.fullmatch(name):
            raise TemplateError(
                f"line_forms declares {name!r}, which is not a form's name: a "
                f"dotted name, as actions.verdict")
        where = f"line_forms.{name}"
        held = _entry(entry, where, _FORM_KEYS)
        template = _read(held["text"], where)
        if template.defers:
            raise TemplateError(
                f"{where} names {{{_BENEATH}}}, and a type's default is the layer "
                f"every other stands over: there is nothing beneath it")
        _names_declared(template, where, declared)
        read.append(Form(name, _sentence(held["sentence"], where), str(held["text"]),
                         template))
    return Declarations(tuple(read), declared.words, declared.fields)


def read_display(block: object) -> dict[str, str]:
    """A check's ``display:`` block as its YAML writes it: a form's full name to the
    template that re-words it — absent or empty, nothing re-worded. Another shape is
    refused, naming the place; which names are the type's forms, and what each
    template may name, is :func:`resolve`'s to say over the type's declarations."""
    if block is None:
        return {}
    if not isinstance(block, Mapping):
        raise TemplateError(
            f"display maps a form's full name to the template that re-words it, and "
            f"is {type(block).__name__}")
    read: dict[str, str] = {}
    for name, text in block.items():
        if not isinstance(name, str):
            raise TemplateError(f"display names {name!r}, which is not a form's name")
        if isinstance(text, Mapping):
            raise TemplateError(
                f"display.{name} is a block, and display is keyed flat by a form's "
                f"full name, as '{name}.{next(iter(text), '…')}'")
        if not isinstance(text, str):
            raise TemplateError(
                f"display.{name} must be a template, a line's text, not {text!r}")
        read[name] = text
    return read


def resolve(declarations: Declarations,
            display: Mapping[str, str]) -> dict[str, Wording]:
    """What each of a type's forms says on one check: the deployment's template over
    the type's default where ``display`` re-words the form, and the default where it
    does not. A name in ``display`` that is no form of the type, and a template that
    names what the type does not declare, are refused (decision 5)."""
    forms = {form.name: form for form in declarations.forms}
    for name in display:
        if not forms:
            raise TemplateError(
                f"display re-words {name!r}, and this type declares no form for a "
                f"template to re-word")
        if name not in forms:
            raise TemplateError(
                f"display re-words {name!r}, which is no form of this type; its "
                f"forms are {', '.join(forms)}")
    wordings: dict[str, Wording] = {}
    for form in declarations.forms:
        text = display.get(form.name)
        if text is None:
            wordings[form.name] = Wording(form.template)
            continue
        where = f"display.{form.name}"
        template = _read(text, where)
        _names_declared(template, where, declarations)
        wordings[form.name] = Wording(template, form.template)
    return wordings
