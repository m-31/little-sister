"""The Content-Security-Policy, assembled rather than written (ADR-0048).

A policy is one response header, and setting it is one line. That is the trap: the
header is a *promise about how the pages are built*, and the only policy worth having
is a strict one. A strict policy has to name every origin a page reaches — and the
origins a **dependent package** reaches cannot be known here. A filler that raises a
ticket calls an issue tracker; a check may embed an image from its own service in the
text it reports; the packaging phase will bring plugins with an API and an identity
provider of their own. A policy hardcoded in this library would leave such a package
unbuildable or force a fork, and the shape of a header deployments already depend on
is expensive to revise afterwards.

So there is **no policy constant**. This module holds the library's :data:`DEFAULTS`,
the contributions packages make to them, and the deployment's own last word; the
header value is composed by :func:`assemble` **at application creation** — after every
registration has run and the configuration is loaded. Nothing is computed at import,
because import is when contributions are still arriving.

What made this tractable is ADR-0037: ``script-src`` names **origins, not files**, and
a registered extension asset is served from our own origin, so ``'self'`` already
covers every filler's code — including code this library will never see. The open
question was only ever what a package *reaches*.

Three rules keep a contribution safe to accept:

* **An origin, never a keyword.** ``'unsafe-inline'`` and friends are refused from a
  package: one dependency able to switch the policy off would make it decorative for
  every other package in the process. Only the deployment may take that cost, in its
  own configuration (:func:`configured`).
* **A deployment-specific host is declared, not written.** :func:`origin_of` points at
  a field in the package's own configuration aspect, so the host is written once and
  cannot drift out of the file an operator edits.
* **Every refusal is a warning and a skip**, like every other registration seam here.
  A malformed source never prevents startup — and never silently widens the policy
  either.

The first policy shipped is ``Content-Security-Policy-Report-Only`` (the header name
is the caller's; this module only builds the value): violations are logged, nothing is
blocked, and what enforcement would then cost is a separate, later decision.
"""
from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from little_sister.config_dir import ASPECTS, aspect_files
from little_sister.logger import logger

#: The deployment's own aspect (ADR-0031): ``config/csp.yaml``, a mapping of directive
#: to a list of sources. Layered across the path-list like ``actions`` — a site root
#: **adds** its sources to a base root's, because a policy is a union by nature and
#: there is nothing to overwrite.
CSP_ASPECT = "csp"

#: Where the browser posts a violation report. Login-free by necessity: a violation on
#: the login page has no session to authenticate with.
REPORT_PATH = "/csp-report"

#: The ``by`` of a source the library itself puts in the policy.
LIBRARY = "little-sister"

#: The CDN that serves Bootstrap (every page) and Floating UI (the dashboard). It is a
#: **script** source as much as a style one. Named here rather than repeated: whether
#: to vendor these instead is the enforcement question, not this one.
CDN = "https://cdn.jsdelivr.net"

#: The library's own floor: what *our* pages need, and nothing else. Every value is a
#: source list except ``report-uri``, which is where a violation goes.
#:
#: Two deliberate choices, both of which a strict policy would revisit:
#:
#: * ``style-src`` keeps ``'unsafe-inline'``. Several inline ``style=`` attributes
#:   carry *computed* values — a card's reason-line cap, the ring geometry on
#:   ``/about`` — and a computed attribute cannot be hashed even in principle. An
#:   inline style is also not the vector a reason line is; reporting it on every page
#:   view would drown the log in the one violation nobody can act on.
#: * ``img-src`` is deliberately strict. Markdown images are on and unconstrained
#:   (ADR-0018), so a note's external image makes every viewer's browser announce
#:   itself to that host. This is the directive with something to measure, and a
#:   deployment that legitimately embeds one adds the host in its own
#:   ``config/csp.yaml``.
DEFAULTS: Mapping[str, tuple[str, ...]] = {
    "default-src": ("'self'",),
    "script-src": ("'self'", CDN),
    "style-src": ("'self'", CDN, "'unsafe-inline'"),
    "img-src": ("'self'",),
    "font-src": ("'self'",),
    # The ~10s fragment poll, and nothing else, is same-origin fetch.
    "connect-src": ("'self'",),
    "form-action": ("'self'",),
    "base-uri": ("'self'",),
    "frame-ancestors": ("'self'",),
    "object-src": ("'none'",),
    # Not a source list: where a violation report is posted.
    "report-uri": (REPORT_PATH,),
}

#: The directives a **package** may add to. A short roster, for the same reason the
#: slot roster is closed: a contribution to a directive the header does not carry would
#: be accepted and then silently dropped. A directive joins this set when something
#: needs it — that is an additive change, where removing one would not be.
#:
#: ``default-src`` is deliberately absent: widening it widens every directive that
#: falls back to it, so a package that needs images says ``img-src``. ``base-uri``,
#: ``frame-ancestors``, ``object-src`` and ``report-uri`` are about *our* document, not
#: about anything an extension reaches.
CONTRIBUTABLE = frozenset({
    "script-src", "style-src", "img-src", "font-src", "connect-src", "form-action",
})

#: Source keywords a policy understands. A package may use none of them (decision 3);
#: the deployment's own configuration is the one place they are taken at all.
KEYWORDS = frozenset({
    "'self'", "'none'", "'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'",
    "'strict-dynamic'", "'report-sample'", "'wasm-unsafe-eval'",
})

#: A bare scheme source (``data:``, ``blob:``, ``https:``) — a keyword by any other
#: name, since ``https:`` allows every host there is. Refused from a package with the
#: keywords, for the same reason.
_SCHEME_SOURCE = re.compile(r"[a-z][a-z0-9+.-]*:$")

#: The schemes an origin may name. Short on purpose, like every other roster here: a
#: browser fetches over these, and a source naming `javascript:` or `file:` is either a
#: mistake or an attempt. A scheme joins the list when something needs it.
FETCH_SCHEMES = frozenset({"http", "https", "ws", "wss"})

#: What may appear in **no** source, on either path. A policy separates sources by
#: whitespace and directives by ``;``, so a string holding either is not one source —
#: whoever wrote it would be appending directives of its own. A control character is
#: worse than wrong: a header value carrying one cannot be assigned, so it would take
#: every page down at request time rather than failing at startup.
_FORBIDDEN = re.compile(r"[\x00-\x20;,\x7f-\x9f]")

#: A host, once the parse has reduced it: dotted labels, an IPv4 literal, or the
#: unwrapped form of an IPv6 one. No wildcard — a package names one host.
_HOST = re.compile(r"[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?|[0-9A-Fa-f:.]+")

#: ``*.example.org`` — a wildcard **subdomain**, which is a legitimate source but not
#: an origin, so only the deployment's own file may write one.
_WILDCARD_HOST = re.compile(r"(?:[a-z][a-z0-9+.-]*://)?\*\.[A-Za-z0-9.-]+(?::\d+)?")

#: A quoted hash or nonce source, which the library may add for its own inline script.
_HASHED = re.compile(r"'(?:sha256|sha384|sha512)-[A-Za-z0-9+/]+={0,2}'|'nonce-[^']+'")

#: ``<aspect>.<field>`` — what :func:`origin_of` names. The field may be dotted, so a
#: package whose configuration nests one level deep can still point at it.
_REFERENCE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+")


@dataclass(frozen=True)
class OriginRef:
    """A deployment-specific origin named by **where it is configured**, not by value.

    A hosted tracker has a fixed origin, but a self-hosted one is the deployment's —
    and it already lives in the filler package's own configuration aspect (ADR-0035).
    Repeating the value here would drift the first time a deployment repointed it, and
    the drift would surface as a blocked request nobody connects to the edit.

    Resolved at assembly and reduced to ``scheme://host[:port]``: whatever the field
    holds is usually a base URL with a path, and a path means nothing to a source list.
    """
    reference: str

    def __str__(self) -> str:
        return f"origin_of({self.reference!r})"


@dataclass(frozen=True)
class Source:
    """One source in the assembled policy, and who is answerable for it.

    ``by`` is what makes the ``/system`` readout worth having: a request blocked inside
    somebody else's package is otherwise undebuggable from the running instance.
    """
    value: str
    by: str


@dataclass(frozen=True)
class Contribution:
    """One accepted ``allow()`` call, before assembly resolves it."""
    directive: str
    source: str | OriginRef
    by: str


@dataclass(frozen=True)
class Policy:
    """An assembled policy: the directives, in order, with each source's contributor."""
    directives: tuple[tuple[str, tuple[Source, ...]], ...]

    def header(self) -> str:
        """The header **value** — what goes after ``Content-Security-Policy…:``."""
        return "; ".join(
            f"{directive} {' '.join(source.value for source in sources)}"
            for directive, sources in self.directives if sources)

    def sources_of(self, directive: str) -> tuple[str, ...]:
        """Just the source strings of one directive — for a test, or a caller that
        does not care who contributed them."""
        for name, sources in self.directives:
            if name == directive:
                return tuple(source.value for source in sources)
        return ()


#: Accepted contributions, in registration order — so a deployment reading ``/system``
#: sees them in the order its wrapper made them.
_contributions: list[Contribution] = []


def allow(directive: str, source: str | OriginRef, *, by: str) -> None:
    """Add one source to one directive of the assembled policy (ADR-0048 §2).

    Called from the same import-before-app slot a package already uses to register
    check types, fillers, assets, icon packs, aspects and secret resolvers::

        from little_sister import csp

        csp.allow("connect-src", "https://api.example-tracker.com", by="ls_tickets")
        csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="ls_tickets")

    ``by`` names the contributor, for the ``/system`` readout. A refusal is a warning
    and a skip: a malformed source costs the deployment its feature, never its
    monitoring — and never quietly widens the policy either.
    """
    if directive not in CONTRIBUTABLE:
        known = ", ".join(sorted(CONTRIBUTABLE))
        if directive in DEFAULTS:
            logger.warning(
                "csp: %s contributes to %r, which the library keeps to itself — "
                "name the directive the source is actually for (%s) (ADR-0048)",
                by, directive, known)
        else:
            logger.warning(
                "csp: %s contributes to the unknown directive %r — a package may add "
                "to: %s (ADR-0048)", by, directive, known)
        return
    if not by or not by.strip():
        logger.warning(
            "csp: a contribution to %r names no contributor — `by` is what the "
            "/system readout answers \"who asked for this source?\" with, so it is "
            "required (ADR-0048)", directive)
        return
    if isinstance(source, str):
        accepted = _package_origin(source, directive, by)
        if accepted is None:
            return
        source = accepted
    contribution = Contribution(directive=directive, source=source, by=by.strip())
    if contribution in _contributions:
        logger.info("csp: %s already allows %s in %r — ignoring the repeat",
                    by, source, directive)
        return
    _contributions.append(contribution)
    logger.info("csp: %s allows %s in %r (ADR-0048)", by, source, directive)


def origin_of(reference: str) -> OriginRef:
    """Name a deployment-specific origin by the configuration field that holds it
    (ADR-0048 §4) — ``"<aspect>.<field>"``, e.g. ``"tickets.base_url"``.

    Resolved at assembly time out of the named aspect's YAML and reduced to
    ``scheme://host[:port]``; a path, query or fragment is dropped. Where the field
    is declared in several configuration roots the **last** wins, which is what a
    site-specific root layered over a base one is for.

    An unusable reference is a warning at assembly and no source — the same posture as
    a refused ``allow()``. It is not an exception here because the reference cannot be
    checked at call time: the aspect it names is registered by the same
    import-before-app block, possibly after this line.
    """
    return OriginRef(reference=reference.strip())


def contributions() -> tuple[Contribution, ...]:
    """Every accepted contribution, in registration order."""
    return tuple(_contributions)


def forget_contributions() -> None:
    """Drop every contribution. For tests: a source one case allows must not widen
    another case's policy, the way ``forget_fillers`` and ``forget_aspects`` keep the
    other two extension seams from leaking between cases."""
    _contributions.clear()


def configured(config_dir: str | Path | None = None) -> tuple[Contribution, ...]:
    """The deployment's own sources, from the ``csp`` aspect (ADR-0048 §5).

    ``config/csp.yaml`` — a mapping of directive to a list of sources — layered
    across the configuration path-list and **unioned** in that order, the way
    ``actions`` layers: a site root adds to a base root rather than replacing it,
    because a policy is a union and there is nothing here to overwrite.

    This is the **only** place a keyword is taken, and the reason a source nobody
    anticipated is a configuration line rather than a fork. It is also the only place a
    directive the library does not emit is refused rather than merely unused: a
    deployment writing ``frame-src`` would otherwise see it silently vanish.
    """
    found: list[Contribution] = []
    for path in aspect_files(CSP_ASPECT, config_dir):
        for directive, value in _read_aspect(path).items():
            for source in _sources(value):
                text = _configured_source(source, directive, path)
                if text is None:
                    continue
                entry = Contribution(directive=directive, source=text, by=str(path))
                if entry not in found:
                    found.append(entry)
    return tuple(found)


def assemble(*, inline_scripts: tuple[str, ...] = (),
             config_dir: str | Path | None = None) -> Policy:
    """Compose the policy: :data:`DEFAULTS`, then registered contributions, then the
    deployment's configuration.

    Call this **at application creation** — after every registration has run and the
    configuration is loaded. Never at import: import is when contributions are still
    arriving.

    ``inline_scripts`` is the exact text of each inline ``<script>`` the pages carry;
    each becomes a ``'sha256-…'`` in ``script-src``, so the policy names our own
    inline code instead of reporting it forever. The caller passes the text because
    only it has the template environment that renders it — and there is exactly one
    such script (the theme bootstrap), which is why folding its duplicate away was
    worth doing.
    """
    ordered: dict[str, list[Source]] = {
        directive: [Source(value, LIBRARY) for value in sources]
        for directive, sources in DEFAULTS.items()
    }
    for text in inline_scripts:
        ordered["script-src"].append(Source(inline_hash(text), LIBRARY))
    for contribution in (*contributions(), *configured(config_dir)):
        value = (_resolved(contribution.source, contribution.by, config_dir)
                 if isinstance(contribution.source, OriginRef)
                 else contribution.source)
        if value is None:
            continue
        sources = ordered.setdefault(contribution.directive, [])
        if any(source.value == value for source in sources):
            continue
        sources.append(Source(value, contribution.by))
    return Policy(directives=tuple(
        (directive, tuple(_without_none(directive, sources)))
        for directive, sources in ordered.items()))


def inline_hash(text: str) -> str:
    """The ``'sha256-…'`` source for one inline script's exact text.

    A browser hashes the element's text content byte for byte, so what is passed here
    has to be what the document carries — not a re-indented copy of it.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return f"'sha256-{base64.b64encode(digest).decode('ascii')}'"


def _without_none(directive: str, sources: list[Source]) -> list[Source]:
    """``'none'`` beside another source is not a narrower policy — it is an invalid
    one, and a browser ignores the whole directive. If something contributed to a
    directive the library set to ``'none'``, the contribution wins and ``'none'`` goes,
    with a line saying so."""
    if len(sources) < 2:
        return sources
    kept = [source for source in sources if source.value != "'none'"]
    if len(kept) != len(sources):
        logger.warning(
            "csp: %r was 'none' and now names %s — dropping 'none', which is only "
            "valid alone, so this directive is now *wider* than the library's default "
            "(ADR-0048)", directive,
            ", ".join(f"{source.value} ({source.by})" for source in kept))
    return kept


def _origin(text: str, *, reduce: bool = False) -> str | None:
    """``text`` as a bare ``scheme://host[:port]`` origin, or ``None``.

    The one place a source string becomes an origin, so the package path and
    :func:`origin_of` cannot disagree about what one is. The host is **re-derived from
    the parse** rather than trusted as written, because the assembled value is
    whitespace-and-semicolon delimited: a "source" carrying either is not one source,
    it is several, and the last of them could be a directive of its own.

    ``reduce`` is the difference between the two callers. A package writes a source
    literally, so a path or a userinfo there is a mistake and earns ``None`` and a
    message. :func:`origin_of` names a field an operator wrote for their own purposes —
    normally a base URL with a path, sometimes with credentials in it — so there the
    extra parts are *dropped*, which is what decision 4 means by reduced. Credentials
    are dropped either way and never reach a response header.
    """
    parts = urlsplit(text)
    if parts.scheme not in FETCH_SCHEMES:
        return None
    if not reduce and (parts.path or parts.query or parts.fragment or parts.username):
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if host is None or not _HOST.fullmatch(host):
        return None
    if ":" in host:  # an IPv6 literal, which urlsplit unwraps
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def _usable_token(text: str) -> bool:
    """Whether ``text`` can be *one* source in the assembled value at all.

    A policy separates sources by whitespace and directives by ``;``, so a string
    holding either is not a single source — accepting one would let whoever wrote it
    append directives of its own, and a control character would make the header
    unassignable and take every page down with it. This is checked before anything
    else, on both the package and the configuration path.
    """
    return not _FORBIDDEN.search(text)


def _package_origin(source: str, directive: str, by: str) -> str | None:
    """A **package's** literal source as a canonical origin, or ``None`` (decision 3).

    Refused: every keyword, a bare scheme, any ``*``, anything carrying a path or
    userinfo, and anything that is not one whitespace-free token. A source list names
    origins, and a package that thought otherwise should hear so rather than have its
    intent guessed at.

    What comes back is the origin **as the parse sees it** — a scheme and host are
    case-insensitive to a browser, so `HTTPS://A.EXAMPLE` is accepted but stored
    lower-cased; otherwise two packages naming one host in different cases would put
    two entries in the policy and two lines on ``/system``.
    """
    text = source.strip()
    if not _usable_token(text):
        logger.warning(
            "csp: %s contributes %r to %r, which is not a single source — a policy "
            "separates sources by whitespace and directives by ';', so this would "
            "add whatever follows as a source or a directive of its own (ADR-0048)",
            by, text, directive)
        return None
    if text in KEYWORDS or _HASHED.fullmatch(text) or text.startswith("'"):
        logger.warning(
            "csp: %s tries to add the keyword %s to %r — a package contributes an "
            "origin, never a keyword; only the deployment's own config/csp.yaml may "
            "take one, because one dependency able to relax the policy makes it "
            "decorative for every other (ADR-0048)", by, text, directive)
        return None
    if "*" in text or _SCHEME_SOURCE.fullmatch(text):
        logger.warning(
            "csp: %s tries to add %r to %r, which is a wildcard rather than an "
            "origin — a package contributes one named host (ADR-0048)",
            by, text, directive)
        return None
    origin = _origin(text)
    if origin is None:
        reduced = _origin(text, reduce=True)
        if reduced is not None:
            logger.warning(
                "csp: %s contributes %r to %r, but a source list names an origin and "
                "nothing narrower — use %s (ADR-0048)", by, text, directive, reduced)
        else:
            logger.warning(
                "csp: %s contributes %r to %r, which is not an origin — an origin is "
                "scheme://host[:port] over %s (ADR-0048)", by, text, directive,
                "/".join(sorted(FETCH_SCHEMES)))
        return None
    return origin


def _configured_source(source: object, directive: str, path: Path) -> str | None:
    """One source written in ``config/csp.yaml``, stripped — or ``None`` if unusable.

    Looser than :func:`_package_origin` on purpose — this is where a keyword, a bare
    scheme and a wildcard may be taken — but still checked, because a typo in a policy
    is a policy that quietly does not do what its author read, and a source carrying
    whitespace or a ``;`` is not one source at all.
    """
    if directive not in DEFAULTS and directive not in CONTRIBUTABLE:
        logger.warning(
            "csp: %s names the directive %r, which this library does not emit, so "
            "the sources under it would have no effect — known: %s (ADR-0048)",
            path, directive, ", ".join(sorted(set(DEFAULTS) | CONTRIBUTABLE)))
        return None
    if not isinstance(source, str) or not source.strip():
        logger.warning("csp: %s lists %r under %r, which is not a source (ADR-0048)",
                       path, source, directive)
        return None
    text = source.strip()
    if not _usable_token(text):
        logger.warning(
            "csp: %s lists %r under %r, which is not a single source — a policy "
            "separates sources by whitespace and directives by ';'. Write one source "
            "per list entry (ADR-0048)", path, text, directive)
        return None
    if text == "'none'":
        logger.warning(
            "csp: %s lists 'none' under %r, which cannot do what it looks like — a "
            "configured source is **added** to the policy, and 'none' only means "
            "anything when it is the only source a directive has (ADR-0048)",
            path, directive)
        return None
    if (text in KEYWORDS or _HASHED.fullmatch(text) or text == "*"
            or _SCHEME_SOURCE.fullmatch(text)):
        return text
    if text.startswith("'"):
        logger.warning(
            "csp: %s lists %s under %r, which is not a keyword a policy knows — "
            "known: %s (ADR-0048)", path, text, directive,
            ", ".join(sorted(KEYWORDS)))
        return None
    if _origin(text) is not None or _WILDCARD_HOST.fullmatch(text):
        return text
    if text.startswith("/") and directive == "report-uri":
        # the one directive whose value is a path rather than an origin, so the one
        # place a deployment may repoint it
        return text
    logger.warning(
        "csp: %s lists %r under %r, which is neither an origin nor a keyword "
        "(ADR-0048)", path, text, directive)
    return None


def _resolved(reference: OriginRef, by: str,
              config_dir: str | Path | None) -> str | None:
    """One :func:`origin_of` reference, reduced to ``scheme://host[:port]``."""
    text = reference.reference
    if not _REFERENCE.fullmatch(text):
        logger.warning(
            "csp: %s names %r, which is not <aspect>.<field> — the origin of a "
            "deployment-specific host is declared by where it is configured "
            "(ADR-0048)", by, text)
        return None
    aspect, _, field = text.partition(".")
    if aspect not in ASPECTS:
        logger.warning(
            "csp: %s names %r, but %r is not a registered configuration aspect — "
            "register it before the app is imported (ADR-0035), in the same block "
            "as this contribution (ADR-0048)", by, text, aspect)
        return None
    value = _field(aspect, field, config_dir)
    if value is None:
        logger.warning(
            "csp: %s names %r, and config/%s has no %s — the source is skipped "
            "rather than guessed at (ADR-0048)", by, text, aspect, field)
        return None
    origin = _origin(value, reduce=True)
    if origin is None:
        logger.warning(
            "csp: %s names %r, which holds %r — not a URL an origin can be taken "
            "from (ADR-0048)", by, text, value)
        return None
    return origin


def _field(aspect: str, field: str,
           config_dir: str | Path | None) -> str | None:
    """A dotted field out of an aspect's YAML, last configuration root winning.

    Later-root-wins rather than first, because that is what layering a site-specific
    root over a base one is for — the same direction ``settings`` merges in.
    """
    found: str | None = None
    for path in aspect_files(aspect, config_dir):
        current: object = _read_aspect(path)
        for step in field.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(step)
        if isinstance(current, str) and current.strip():
            found = current.strip()
    return found


def _read_aspect(path: Path) -> Mapping[str, object]:
    """One aspect file as a mapping — ``{}`` for anything else, with a warning.

    A directory-form aspect is read as its ``<name>.yaml``, so a package whose
    configuration grew into a directory (ADR-0030's shape) still answers.
    """
    source = path / f"{path.name}.yaml" if path.is_dir() else path
    try:
        with open(source, encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        logger.warning("csp: %s could not be read (%s) — ignored (ADR-0048)",
                       source, error)
        return {}
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        logger.warning(
            "csp: %s is not a mapping of directive to sources — ignored (ADR-0048)",
            source)
        return {}
    return {str(key): value for key, value in loaded.items()}


def _sources(value: object) -> tuple[object, ...]:
    """A directive's value as a tuple, accepting one bare source as well as a list."""
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(value)
    return ()
