"""Addressable reasons: a node's reason list as keyed entries (ADR-0036).

A check that discovers **dynamic entries** — security findings under a severity
band, waiting pull requests under an aspect — puts many of them into one node's
reasons. An operator picks one, opens a ticket and works on it, and the next
engineer has to be able to see that. Maintenance is per node, so pinning the one
finding somebody is on silences the other nineteen. What is needed is narrower
than a node per entry: an entry must be **addressable**, so a pin can name one.

So a reason is a keyed entry, ``slug -> text``, in the check's order — insertion
order, never sorted by key, because the order a check emits its entries in is
information (severity, API order) that an opaque slug would scramble.

**Prose is the default; members are declared.** Not every reason list is a list of
independent things: a failing check's ``check error:`` line and its stack trace,
or stdout beside stderr, are *one condition in several paragraphs*. Silencing the
trace while the message keeps alarming is meaningless. Both kinds are keyed — the
key is how anything addresses a line at all — but only **members** are
individually suppressible; prose keeps the node pin as its unit. A check declares
members by handing over a **mapping** (the shape says so) or by setting
``entries=True`` beside a sequence of strings it knows to be stable.

**An entry may carry a code of its own** (ADR-0042): one node's lines can then
disagree — this workflow failed, that one passed — and the node's own status is
*derived* from them, the roll-up applied one level down. An entry may also carry
``running``, saying its subject has work in flight right now; that is display (a
class and an italic, the words still say it) and never touches the roll-up. Both
travel on :class:`Entry`, the check-facing value object, accepted wherever a
``(slug, text)`` pair is — and an entry that declares either one declares
**members** by shape, the way a mapping does.

Two properties follow, and both are why the default sits on this side: the
engine's failure path needs no change at all, and no existing surface moves until
some check opts in.

**A line also carries what it is about, and what was read.** ``subject`` names the
entity — the repository, the host — as the provider's own identifier, so a view
that groups can group; ``data`` is the **record**, the material the check read and
until now threw away once it had written its sentence. Both are optional, both are
invisible until something renders them, and neither makes a line a member: they are
data about a claim, not a claim.

**Where a declared slug comes from** is the check's to answer, and there are two
answers here: :func:`derived_slug` hashes the text, for a check with nothing
better, and :func:`slug` joins identifiers the provider already owns, for a check
that has them (ADR-0050). Only the second survives a re-wording.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from little_sister.codes import StatusCode, worst_of

# A declared slug is opaque and never rendered as text — it lives in `data-`
# attributes, form fields, query values and log lines — so it stays bounded and
# free of whitespace and control characters (ADR-0036 consequences).
MAX_SLUG_LENGTH = 200

#: The prefix marking a **derived** slug. It is there so a human reading a URL or
#: a log line can tell the two promises apart: a declared slug is an identity
#: claim that survives a re-wording, a derived slug *is* the wording.
DERIVED_PREFIX = "h-"

#: Characters :func:`slug` keeps. Everything else — a branch's ``/``, the space in
#: an entity name, a ``#`` — collapses to a single ``-``. Deliberately narrower
#: than what :func:`_check_declared` validates: a token that needs no escaping
#: *anywhere* is one less thing for a call site that forgets to encode it to get
#: wrong.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: How much of an over-long declared slug is replaced by the disambiguating hash.
_DIGEST_LENGTH = 10

#: The codes an entry may declare (ADR-0042): a check's per-line claim. Never
#: ``MAINTENANCE`` — a pin is admin-authored and *recorded beside* the reading
#: (ADR-0041); a check that could report it could silence itself (ADR-0032 rule 6).
ENTRY_CODES = frozenset({
    StatusCode.OK, StatusCode.WARN, StatusCode.ERROR, StatusCode.UNDEFINED,
})


#: How long a ``subject`` may be. A subject is the provider's identifier for the
#: entity a line is *about* — a repository id, a host name — and not text, so it is
#: bounded like a slug and for the same reason: it travels in ``data-`` attributes,
#: query values and log lines. Only the length and the control characters are
#: checked; what a provider mints is its own business.
MAX_SUBJECT_LENGTH = MAX_SLUG_LENGTH

#: The record keys the surfaces read as an **instant** — to be rendered in the
#: viewer's timezone and as an age. Recognized at **any depth**, because a record
#: is a tree and a time nested under ``completed`` is as much a time as one at the
#: top. The value is an ISO-8601 string carrying an offset, or ``None``; it is
#: converted to UTC here, at the check's seam, and never re-stamped afterwards.
#:
#: Nothing else is typed. A name earns a type when a surface does something with
#: it that it could not do without one, and today exactly one thing qualifies: a
#: time cannot be shown in somebody's own zone unless the reader knows it is a
#: time. A measurement — a number with a unit — is the next candidate and is
#: deliberately not here: its reader is the series that draws it, and the shape a
#: measurement takes is that phase's to settle with a curve in front of it.
RECORD_TIMESTAMP_KEYS = frozenset({"at", "started", "ended"})


class ReasonError(ValueError):
    """A reason list the core cannot key — a mixed sequence, a declared slug
    that is empty, over-long or carries whitespace, an entry code outside a
    check's vocabulary, or a record that is not serializable, too heavy, or
    carries something that is not a time under a name that says it is. Raised
    where the outside world enters (ADR-0026), so a check author sees it at
    construction."""


def check_subject(value: str, what: str) -> None:
    """Refuse a subject that cannot travel — too long, or carrying a control
    character. Raises :class:`ReasonError`.

    Shared by the two places a measurement names its object: an entry's
    ``subject``, and a ``CheckResult``'s, where the object has a node of its own
    (ADR-0085). Only the length and the control characters are checked; what a
    provider mints is its own business.
    """
    if len(value) > MAX_SUBJECT_LENGTH:
        raise ReasonError(
            f"{what} is longer than {MAX_SUBJECT_LENGTH} characters: "
            f"{value[:40]!r}…")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ReasonError(f"{what} carries a control character: {value!r}")


@dataclass(frozen=True)
class Entry:
    """One keyed reason: an opaque ``slug``, the ``text`` that is displayed, and —
    optionally — the entry's own claim (ADR-0042).

    ``text`` is what every existing surface already shows — events, history and
    the JSON envelope carry the values and never the slug (ADR-0036 decision 11):
    a slug in a historical event means nothing once the entry is gone.

    ``subject`` is **what this line is about** — the repository, the host — as the
    provider's own identifier, and it is empty where the check did not say. It
    exists because the subject lives in the model and nowhere in the data: a
    declared slug is built subject-first, but the parts are joined with ``-`` and
    ``-`` is legal inside a part, so ``little-sister-pr-42`` cannot be split back
    apart by anything that did not build it. What needs it is any view that
    **groups** — a box per repository, everything about this one thing. It is
    deliberately **not** an address: nothing may be pinned by subject, because a
    pin holds an identifier and only a line has one, and a subject pin would
    silence twenty findings nobody looked at.

    ``data`` is the **record**: the entity's data as the check saw it, beside the
    sentence the check wrote about it. Today a check reads a workflow run, decides
    a code, writes a line, and everything else it knew is gone; the record is that
    material kept rather than thrown away. It is invisible until something renders
    it — ``text`` is untouched and no card moves — and it is what the line
    template, the grading seam and the series are each built on later. A handful
    of key names carry a type the surfaces know (:data:`RECORD_TIMESTAMP_KEYS`);
    everything else is free-form and renders as key and value. Validated and
    bounded at the ``CheckResult`` seam, which is where the limit lives.

    Neither declares **members**: a record is data, not a claim, so prose that
    carries one stays prose and keeps the node pin as its unit of suppression.

    ``code`` is the entry's **own status** — the verdict of the workflow this line
    stands for, the severity of this finding. ``None`` (the default) means the
    entry carries its node's code, which is every entry that existed before
    ADR-0042 and remains permanently right where the grouping already moved the
    severity onto the node (a severity band). ``running`` says the entry's subject
    has work in flight — display only, never severity.

    This class once said that a third field must argue for itself harder than the
    second, because an entry is deliberately not a node. ``subject`` and ``data``
    are that argument, and the answer to *why not a node* is the one ADR-0036 gave:
    a record needs no path, no pin of its own beyond the entry's, no children and
    no place in the roll-up.
    """
    slug: str
    text: str
    code: StatusCode | None = None
    running: bool = False
    subject: str = ""
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        check_subject(self.subject, "an entry's subject")
        if self.code is not None and self.code not in ENTRY_CODES:
            raise ReasonError(
                f"an entry may not declare {self.code.name}: a pin is recorded "
                f"beside the reading, never reported by a check (ADR-0042)")

    @property
    def derived(self) -> bool:
        """Whether this slug was computed from the text rather than declared. A
        derived slug invalidates itself on a re-wording, which is exactly why no
        separate validator field is needed."""
        return self.slug.startswith(DERIVED_PREFIX)


#: Backward-compatible name — the internal form and the check-facing value object
#: are one class (ADR-0042 names it ``Entry``; ADR-0036-era code says
#: ``ReasonEntry``). One object, two spellings, zero migration.
ReasonEntry = Entry

#: Everything a check (or a direct `upsert` caller) may hand over as a reason.
#: Four input forms, one internal one — the normalization below is the only place
#: that knows the difference.
ReasonInput = (
    str
    | Mapping[str, str]
    | Sequence[str]
    | Sequence[tuple[str, str]]
    | Sequence[Entry]
    | None
)


# Inline-active Markdown punctuation: emphasis (*), code spans (`), links and the
# escape char itself ([ ] \). Escaping these neutralises the constructs that turn
# untrusted text into formatting or a link. Linkification also recognizes a bare
# HTTP(S) scheme, so ``plain`` breaks that scheme token without changing its rendered
# text. Deliberately omitted: raw HTML and unsafe link schemes (already handled by
# the renderer — html-off, validated links, ADR-0018); ``_`` (literal between word
# characters in CommonMark, so ``MD0_DATA`` / ``debug_df_raw`` stay clean); and block
# markers (#, -, >) which are at worst cosmetic — keeping everyday text free of
# escape noise.
_MD_ESCAPE = {ord(ch): f"\\{ch}" for ch in "\\`*[]"}
_WEB_URL_SCHEME = re.compile(r"\bhttps?://", re.IGNORECASE)


def plain(text: object) -> str:
    """Escape inline Markdown so untrusted text — a path, an error, a captured
    line — renders **literally** in an entry (ADR-0018). Use it when folding
    external output into a line, a check's reason or the instance's own report
    alike; for multi-line / log output prefer :func:`little_sister.checks.code`.
    Here rather than in the check layer because the modules beneath it — a
    configuration loader, the identity doors — fold paths and errors into
    self-report lines too."""
    escaped = str(text).translate(_MD_ESCAPE)
    return _WEB_URL_SCHEME.sub(
        lambda match: match.group().replace(":", r"\:"), escaped)


def derived_slug(text: str) -> str:
    """The content-hash slug for ``text`` — ``h-`` plus ten hex digits of its SHA-1.

    Deliberately **not** an index: an index moves when an entry is inserted above
    it, so a pin would slide silently onto a *different* finding, with nothing to
    notice it by. A hash makes "return a stable string" sufficient — a check that
    emits ``f"{issue_id} {text}"`` gets durable pins without a line of slug logic.
    """
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
    return DERIVED_PREFIX + digest[:10]


def _narrow(part: object) -> str:
    """One slug part, reduced to characters that need no escaping anywhere.

    A part that keeps nothing but *had* something becomes a hash of itself. The
    alternative is silence: it would drop out like a blank part, two findings that
    differ only there would land on one slug, and `_dedupe` would separate them by
    position — the failure ADR-0050 is written to prevent.
    """
    raw = str(part)
    kept = _UNSAFE.sub("-", raw).strip("-.")
    if kept or not raw.strip():
        return kept
    return hashlib.sha1(raw.encode("utf-8"),
                        usedforsecurity=False).hexdigest()[:_DIGEST_LENGTH]


def slug(*parts: object) -> str:
    """A **declared** slug from the identifying ``parts`` — ``slug(repo, "pr", 42)``.

    The counterpart of :func:`derived_slug`, for the check that has something
    better than its own wording: the identifiers the provider already owns
    (ADR-0050). Each part is narrowed to ``[A-Za-z0-9._-]`` and joined with ``-``,
    so a branch's ``/`` and the space in an entity name never reach a ``?reason=``
    value — the result needs no escaping anywhere, and passes :func:`normalize`
    by construction.

    Empty parts drop out — ``None``, and anything that is blank — so a missing
    branch or entity leaves no dangling separator. A part that is *not* blank but
    keeps nothing (an entity named in Cyrillic, in Japanese, in emoji) is replaced
    by a hash of itself rather than vanishing: a vanished part would collapse two
    findings onto one slug, and :func:`normalize` would then tell them apart by
    their *position* in the list. An over-long result is bounded the same way, a
    readable prefix plus a hash of the **whole** value, because plain truncation
    maps two long repository names onto one slug for the same reason.

    What is **not** bounded: two parts that differ only in the characters the
    narrowing collapses (``a/b`` and ``a-b``) still meet. Every part is meant to be
    an identifier the provider minted, and those are ASCII and separator-free by
    construction — hashing every part that merely *changed* would be the fix, and it
    would re-point every pin holding a slug built from a branch name today.

    Raises :class:`ValueError` when every part is blank. That is a call-site bug,
    not a data condition: each caller passes at least one literal aspect word.

    One overlap, stated rather than papered over: :attr:`Entry.derived` reads the
    ``h-`` prefix, so a declared slug whose first part is ``h`` answers *yes* to a
    question it should answer no to. The property is advisory — nothing routes on
    it — and rewriting the token would be worse: a slug is a stored key, and the
    fix would silently re-point every pin holding the old one.
    """
    cleaned = [_narrow(part) for part in parts if part is not None]
    joined = "-".join(part for part in cleaned if part)
    if not joined:
        raise ValueError("a slug needs at least one non-empty part")
    if len(joined) > MAX_SLUG_LENGTH:
        digest = hashlib.sha1(joined.encode("utf-8"),
                              usedforsecurity=False).hexdigest()[:_DIGEST_LENGTH]
        joined = f"{joined[:MAX_SLUG_LENGTH - _DIGEST_LENGTH - 1]}-{digest}"
    return joined


def derive_code(entries: Sequence[Entry]) -> StatusCode:
    """The node code a coded entry set derives to (ADR-0042).

    Worst-of over the entries' **own** codes; an entry that declares none
    contributes nothing here (it carries the node's — that is, the value this
    function returns); ``UNDEFINED`` is ignored, as everywhere (ADR-0039). On an
    **entry** that code means *this line makes no claim about its subject* — a
    claim withheld on purpose (ADR-0060), which is a different sentence from the
    node-level *nothing has reported yet* and skipped for the same reason. Two
    stated tie-breaks: entries whose codes are all ``UNDEFINED`` leave the node
    ``UNDEFINED`` — every line withheld its claim, which is when ADR-0060 says the
    check owes its own node a ``WARN`` — while an **empty** entry set reads
    ``OK``: the check ran, enumerated, and found
    nothing, and "nothing to report" is not "nothing reported". Pins do not reach
    this function — suppression is joined at snapshot time (ADR-0032 rule 3).
    """
    counted = [entry.code for entry in entries
               if entry.code is not None and entry.code is not StatusCode.UNDEFINED]
    if counted:
        return worst_of(counted)
    if any(entry.code is StatusCode.UNDEFINED for entry in entries):
        return StatusCode.UNDEFINED
    return StatusCode.OK


def _record_instant(value: object, where: str) -> str | None:
    """One value under a :data:`RECORD_TIMESTAMP_KEYS` name, as UTC — or ``None``.

    ``None`` is kept rather than refused: *this run has not ended* is a fact, and
    refusing it would push a check into omitting the key, which loses the
    difference between a time that is absent and one that was never asked for.

    An **offset is required**. A naive stamp is an instant only to whoever wrote
    it; the node's own timestamp may be naive-local because one process owns it
    (ADR-0006), but a record's time comes from somebody else's clock and travels
    to a viewer in a third zone.
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            moment = None
        if moment is not None and moment.tzinfo is not None:
            return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise ReasonError(
        f"record field {where!r} names a time, so its value must be an ISO-8601 "
        f"string carrying an offset, or null: {value!r}")


def _walked(value: object, path: str) -> object:
    """The record, one node at a time, with every timed field converted."""
    if isinstance(value, Mapping):
        walked: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            where = f"{path}.{name}" if path else name
            walked[name] = (_record_instant(item, where)
                            if name in RECORD_TIMESTAMP_KEYS
                            else _walked(item, where))
        return walked
    if isinstance(value, (list, tuple)):
        return [_walked(item, f"{path}[{index}]")
                for index, item in enumerate(value)]
    return value


def normalize_record(data: object, *, limit: int) -> dict[str, Any]:
    """Validate one entry's record and answer the copy the tree will hold.

    Three steps, and the order is the point. The record is **walked** once, so a
    value under a timed name is an instant in UTC or nothing. It is then
    **serialized**, which proves the JSON-serializable promise the field makes and
    measures it: ``limit`` is counted in the bytes of that JSON, because those are
    what a record actually costs — the envelope sent to every client, and a series
    file later. And it is **read back**, so what the tree holds is plain JSON types
    that nobody outside owns.

    That last step is not tidiness. A snapshot is read outside the lock (ADR-0002),
    so a check keeping a reference to the mapping it handed over could otherwise
    change a value while a page renders it. Reading the JSON back also makes what
    is stored exactly what a client will receive — a tuple arrives as a list, a
    non-string key as a string — rather than something that merely serializes to it.

    An over-heavy record refuses the **whole result**, loudly, the way a
    declared-and-derived code does: a silently dropped record would be believed
    missing. The check author meets it on the first run, with the size in the
    message, and shapes the record to fit.
    """
    if not isinstance(data, Mapping):
        raise ReasonError(
            f"an entry's record must be a mapping of fields, not "
            f"{type(data).__name__}")
    try:
        encoded = json.dumps(_walked(data, ""), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ReasonError(
            f"an entry's record must be JSON-serializable: {error}") from error
    size = len(encoded.encode("utf-8"))
    if size > limit:
        raise ReasonError(
            f"an entry's record is {size:,} bytes and the limit is {limit:,}: a "
            f"record is what the check read about one subject, never a payload "
            f"dump")
    record: dict[str, Any] = json.loads(encoded)
    return record


def _check_declared(slug: str) -> str:
    """Validate a check-supplied slug, or raise. A declared slug is an identity
    claim and travels in URLs and form fields, so it has to be usable as one."""
    if not slug or slug != slug.strip() or any(ch.isspace() for ch in slug):
        raise ReasonError(f"reason slug must be non-empty and free of whitespace: "
                          f"{slug!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in slug):
        raise ReasonError(f"reason slug carries a control character: {slug!r}")
    if len(slug) > MAX_SLUG_LENGTH:
        raise ReasonError(f"reason slug longer than {MAX_SLUG_LENGTH} characters: "
                          f"{slug[:40]!r}…")
    return slug


def _dedupe(entries: Sequence[Entry]) -> tuple[Entry, ...]:
    """Resolve a slug already taken within this node to ``-2``, ``-3``, in the
    check's order — everything else on the entry travels unchanged.

    The suffix covers both an honestly repeated text — a real list can carry the
    same sentence three times, for three different findings — and an
    astronomically unlikely hash collision.
    """
    out: list[Entry] = []
    seen: set[str] = set()
    for entry in entries:
        candidate, bump = entry.slug, 1
        while candidate in seen:
            bump += 1
            candidate = f"{entry.slug}-{bump}"
        seen.add(candidate)
        out.append(entry if candidate == entry.slug
                   else replace(entry, slug=candidate))
    return tuple(out)


def _keyed(pairs: Sequence[tuple[str, str]]) -> tuple[Entry, ...]:
    """Build plain entries from ``(slug, text)`` pairs and dedupe them."""
    return _dedupe([Entry(slug, text) for slug, text in pairs])


def normalize(reason: ReasonInput, entries: bool = False, *,
              record_limit: int | None = None) -> tuple[tuple[Entry, ...], bool]:
    """Normalize any accepted reason form into ``(entries, members)``.

    ``members`` says the entries are **individually suppressible**. A mapping or a
    pairs sequence says so by its shape; a sequence of plain strings needs the
    ``entries`` flag; a bare ``str`` is one condition and the flag is meaningless
    beside it. A sequence of :class:`Entry` carries the flag through — and an
    entry declaring a ``code`` or ``running`` declares members by shape
    (ADR-0042), since a per-line claim on an indivisible condition would be
    meaningless. A ``subject`` or a record declares nothing: both are data about
    the line rather than a claim it makes, so prose carrying one stays prose.
    Entry slugs are validated and deduped exactly like declared pairs (a derived
    slug passes its own rules by construction).

    ``record_limit`` turns record validation on and is what the ``CheckResult``
    seam passes; without it records travel as handed over, which is right for the
    internal callers that re-normalize entries this function already built.
    """
    if reason is None:
        return (), False
    if isinstance(reason, str):
        return _keyed([(derived_slug(reason), reason)]), False
    if isinstance(reason, Mapping):
        # An empty mapping declares nothing: a node with no reasons is outside the
        # virtual-child rule either way, so it should not claim to have members.
        lines = _keyed([(_check_declared(str(slug)), str(text))
                        for slug, text in reason.items()])
        return lines, bool(lines)
    items = list(reason)
    if not items:
        return (), False
    if all(isinstance(item, Entry) for item in items):
        typed = [item for item in items if isinstance(item, Entry)]
        for item in typed:
            _check_declared(item.slug)
        if record_limit is not None:
            typed = [
                item if item.data is None else replace(
                    item, data=normalize_record(item.data, limit=record_limit))
                for item in typed]
        deduped = _dedupe(typed)
        members = entries or any(
            item.code is not None or item.running for item in deduped)
        return deduped, members
    if all(isinstance(item, str) for item in items):
        texts = [item for item in items if isinstance(item, str)]
        return _keyed([(derived_slug(text), text) for text in texts]), entries
    if all(isinstance(item, tuple) and len(item) == 2 for item in items):
        pairs = [item for item in items if isinstance(item, tuple)]
        return _keyed([(_check_declared(str(slug)), str(text))
                       for slug, text in pairs]), True
    raise ReasonError(
        "a reason sequence must be all strings, all (slug, text) pairs or all "
        "Entry — not a mixture")
