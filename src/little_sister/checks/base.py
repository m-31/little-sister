"""Check abstraction: the base class, result type, config parsing and registry.

A check determines the status of one thing and returns a :class:`CheckResult`.
Subclasses register a ``type`` name; the loader instantiates them from YAML
(see ``loader.py``). Config fields common to every check: ``path``, ``name``,
``description``, ``frequency``, ``timeout`` (project.md §2.5), plus the
optional failure retry — ``retry_interval`` / ``retry_attempts`` (ADR-0033).
"""
from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from little_sister import secrets
from little_sister.errors import CheckError as CheckError
from little_sister.reasons import (
    ReasonEntry,
    ReasonError,
    ReasonInput,
    normalize,
)
from little_sister.status import StatusCode, join_path, leaf_name, split_path

DEFAULT_FREQUENCY_SECONDS = 900   # 15 minutes — most checks run infrequently
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class CheckResult:
    """The outcome of running a check: a code and, when not OK, a reason.

    A result is a small **tree of values**, mirroring the shape of the status
    tree without being one. Most checks return a single leaf
    (``CheckResult(code, reason)``); a check that reports several aspects returns
    ``children`` — each a named ``CheckResult`` the engine upserts beneath the
    check's node (e.g. ``host.disk``, ``host.memory``). It stays a pure value:
    identity (the full path), observation time, maintenance and event-on-change
    are the tree's to set, not the check's (see ADR-0007). ``name`` identifies a
    child relative to its parent and is ignored on the root (the engine places the
    root at ``check.path``); ``description`` is inherited metadata for the
    node, and ``config`` is the parameters the check ran with — display metadata
    (Markdown) carried onto the node like ``description`` (ADR-0013).

    ``reason`` is **keyed** (ADR-0036): a check may hand over a plain string, a
    list of strings, a ``{slug: text}`` mapping or a list of ``(slug, text)``
    pairs, and ``__post_init__`` normalizes all four into ``reason_entries``.
    A mapping or a pairs list declares its entries **members** — individually
    suppressible, so an operator can pin the one finding they are working on; a
    sequence of strings needs ``entries=True`` to say the same, which exists so a
    check whose strings already carry identity (``f"{issue_id} {text}"``) gets
    per-entry pins without restructuring its return. Everything else is **prose**:
    keyed like all reasons, but one condition in several paragraphs, whose unit of
    suppression stays the node pin.

    ``about`` (subject metadata — what the node *is*) and ``title`` (a short
    display label) are the **type-inherent** labels a branch check gives the
    subnodes it emits (ADR-0025) — e.g. a metrics check captioning its ``disk`` /
    ``memory`` aspects. Like ``name`` they are **ignored on the root** (whose
    labels keep their ``nodes.yaml`` / inline-check sources), and unlike
    ``description`` / ``config`` they **fill an empty node field only**: a
    ``nodes.yaml`` declaration seeded at startup always wins, and the label
    freezes at its first fill (stable identity, not live status — text that
    changes with the observation belongs in ``reason``).
    """
    code: StatusCode
    reason: ReasonInput = field(default_factory=list)
    name: str = ""
    description: str = ""
    children: tuple[CheckResult, ...] = ()
    config: str = ""
    about: str = ""
    title: str = ""
    entries: bool = False
    #: Derived in :meth:`__post_init__` — the one internal form (ADR-0036).
    reason_entries: tuple[ReasonEntry, ...] = field(
        init=False, default=(), repr=False, compare=False)
    members: bool = field(init=False, default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for child in self.children:
            if not child.name:
                raise CheckError("a child CheckResult must have a 'name'")
        # Normalize where the outside world enters (ADR-0026): four accepted input
        # forms, one internal one. A malformed slug is the check author's error and
        # surfaces as a failing check, not as a silent re-key.
        try:
            entries, members = normalize(self.reason, self.entries)
        except ReasonError as error:
            raise CheckError(str(error)) from error
        object.__setattr__(self, "reason_entries", entries)
        object.__setattr__(self, "members", members)

    @property
    def reason_texts(self) -> list[str]:
        """The reason texts in the check's order, whatever form was handed over."""
        return [entry.text for entry in self.reason_entries]


CHECK_TYPES: dict[str, type[Check]] = {}


def register(type_name: str) -> Callable[[type[Check]], type[Check]]:
    """Class decorator registering a check under its ``type`` name."""
    def decorator(cls: type[Check]) -> type[Check]:
        cls.type_name = type_name
        CHECK_TYPES[type_name] = cls
        return cls
    return decorator


class Check(abc.ABC):
    """Base class for all checks.

    A check knows where it writes in the tree (``path``), how often it runs
    (``frequency_seconds``), how long to wait (``timeout_seconds``) and how to
    produce a result (:meth:`run`).
    """

    type_name: ClassVar[str] = ""

    def __init__(self, *, path: str, description: str = "",
                 about: str = "", title: str = "",
                 frequency_seconds: int = DEFAULT_FREQUENCY_SECONDS,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 retry_interval_seconds: int | None = None,
                 retry_attempts: int | None = None) -> None:
        # The check's full, absolute node path (ADR-0016); `name` is the last segment.
        self.path = join_path(path)
        self.description = description
        # Inline node metadata (nodes.yaml overrides each): `about` is subject
        # metadata (ADR-0012), `title` a short display label (ADR-0017).
        self.about = about
        self.title = title
        self.frequency_seconds = frequency_seconds
        self.timeout_seconds = timeout_seconds
        # The budgeted failure retry (ADR-0033): while the last result is not
        # OK the engine schedules this check at `retry_interval_seconds`
        # instead of its frequency, at most `retry_attempts` times per failure
        # episode. ``None`` inherits the settings-level default; ``0`` switches
        # the retry off for this check.
        self.retry_interval_seconds = retry_interval_seconds
        self.retry_attempts = retry_attempts
        # Failures from resolve-at-construction secret references (ADR-0023):
        # non-empty ⇒ the engine pins this check to ERROR and never calls run().
        self.secret_errors: list[str] = []

    @property
    def name(self) -> str:
        """This check's node name — the last segment of its path (ADR-0016)."""
        return leaf_name(self.path)

    def owned_nodes(self) -> set[str]:
        """The tree nodes this check gives a definite status to, each the root of
        the subtree it owns (ADR-0015). The loader rejects a union in which two
        checks own overlapping nodes. A leaf check owns just its own node; a
        **branch** check overrides this to own its child subtrees and **not** the
        shared container node it merely rolls up — so peers (e.g. ``host-metrics``
        + ``qnap-metrics``) coexist on one host node, while a duplicate or a leaf
        placed on that container is caught."""
        return {self.path}

    def config_summary(self) -> str:
        """The curated parameters this check ran with, as Markdown, for its detail
        page (ADR-0013). Operator-authored and safe for all viewers — secrets stay
        in ``.env`` (ADR-0003). Override to declare a small allow-list (see
        :func:`config_markdown`); the default is empty. A **branch** check leaves
        this empty (its container node is shared) and tags each child result's
        ``config`` instead."""
        return ""

    def resolve_secret(self, reference: str) -> str:
        """Resolve a secret reference **at construction time** (ADR-0023).

        A bare name reads that environment variable (``.env``, ADR-0003); a
        ``scheme://address`` reference goes through the resolver the
        application registered (``little_sister.secrets``). Call this from
        ``__init__`` / ``_extra_from_config`` and keep the value — never
        resolve during :meth:`run` (cloud stores bill per read; rotation is a
        restart).

        A **malformed** reference (unknown scheme) raises :class:`CheckError`,
        so the load fails loudly like any config typo. A well-formed reference
        that **fails to resolve** (store unreachable, secret absent) is
        recorded in ``secret_errors`` and returns ``""`` — the engine then pins
        this check to a visible ERROR without ever calling :meth:`run`.
        """
        try:
            return secrets.resolve(reference)
        except secrets.UnknownSchemeError as error:
            raise CheckError(str(error)) from error
        except secrets.SecretError as error:
            self.secret_errors.append(str(error))
            return ""

    @abc.abstractmethod
    def run(self) -> CheckResult:
        """Perform the check. A non-OK result must carry a reason (§2.7)."""

    # --- construction from config ---

    @classmethod
    def from_config(cls, config: dict[str, Any], base_dir: Path) -> Check:
        common = _parse_common(config)
        extra = cls._extra_from_config(config, base_dir)
        return cls(**common, **extra)

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        """Subclass hook: parse type-specific config into constructor kwargs."""
        return {}


def _parse_common(config: dict[str, Any]) -> dict[str, Any]:
    """Parse the fields every check shares.

    A node is addressed by one **absolute, slash-separated** ``path`` — e.g.
    ``/system/alpha`` — whose last segment is the node's name (ADR-0016).
    """
    if "name" in config:
        raise CheckError(
            "'name' was merged into 'path' (ADR-0016); give one absolute path "
            "such as '/system/alpha'")
    path = join_path(str(config.get("path", "")))
    if not split_path(path):
        raise CheckError("check config must define a non-empty 'path'")
    return {
        "path": path,
        "description": str(config.get("description", "")),
        "about": str(config.get("about", "")),
        "title": str(config.get("title", "")),
        "frequency_seconds": parse_duration(
            config.get("frequency"), DEFAULT_FREQUENCY_SECONDS),
        "timeout_seconds": float(parse_duration(
            config.get("timeout"), int(DEFAULT_TIMEOUT_SECONDS))),
        # the budgeted failure retry (ADR-0033): absent (None) inherits the
        # settings-level default; a present junk value fails the load, like a
        # bad frequency would
        "retry_interval_seconds": (
            None if config.get("retry_interval") is None
            else parse_duration(config.get("retry_interval"), 0)),
        "retry_attempts": _parse_retry_attempts(config.get("retry_attempts")),
    }


def _parse_retry_attempts(value: object) -> int | None:
    """The per-check fast-retry budget (ADR-0033): ``None`` (absent) inherits
    the settings-level default; otherwise a non-negative int, where ``0``
    switches the retry off for this check. Junk fails the load like any typo."""
    if value is None:
        return None
    try:
        attempts = int(str(value).strip())
    except ValueError as exc:
        raise CheckError(f"invalid retry_attempts: {value!r}") from exc
    if attempts < 0:
        raise CheckError(f"retry_attempts must be >= 0, got {value!r}")
    return attempts


def parse_duration(value: object, default: int) -> int:
    """Parse a duration into whole seconds.

    Accepts a number (seconds) or a string with an optional unit suffix —
    ``s`` seconds, ``m`` minutes, ``h`` hours, ``d`` days (e.g. ``"15m"``). A
    missing value returns ``default``.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower()
    if not text:
        return default
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if text[-1] in units:
        number, factor = text[:-1], units[text[-1]]
    else:
        number, factor = text, 1
    try:
        return int(float(number) * factor)
    except ValueError as exc:
        raise CheckError(f"invalid duration: {value!r}") from exc


def coerce_code(value: object, default: StatusCode = StatusCode.ERROR) -> StatusCode:
    """Coerce a config value into a StatusCode (case-insensitive name)."""
    if value is None:
        return default
    if isinstance(value, StatusCode):
        return value
    text = str(value).upper()
    if text not in StatusCode.__members__:
        raise CheckError(f"invalid status code: {value!r}")
    return StatusCode[text]


def parse_secret_refs(config: dict[str, Any], *names: str) -> dict[str, str]:
    """Parse a check config's ``secrets:`` block into ``name -> reference``.

    Every credential a check needs is named in this one block, so the references
    sit where a reader looks for them and no ordinary config field ever has to be
    read as "is this a value or the name of one?" (ADR-0023). Each of ``names``
    is **required** — a check that needs a credential says which one, rather than
    inheriting a hard-coded default that quietly ties every instance of the type
    to the same secret; an unrecognized key is a typo and fails the load.

    The values are **references**, not secrets: resolve them with
    :meth:`Check.resolve_secret` from the constructor (this hook is a classmethod;
    resolution needs the instance) and never during a run. No error here quotes a
    value — the field may hold a pasted credential.
    """
    wanted = ", ".join(names)
    block = config.get("secrets")
    if block is None:
        raise CheckError(
            f"check config must define a 'secrets:' block naming: {wanted}")
    if not isinstance(block, dict):
        raise CheckError(
            "'secrets' must be a mapping of name -> secret reference "
            f"(expected: {wanted})")
    unknown = sorted(str(key) for key in block if str(key) not in names)
    if unknown:
        raise CheckError(
            f"unknown key(s) in 'secrets': {', '.join(unknown)} "
            f"(this check takes: {wanted})")
    references: dict[str, str] = {}
    for name in names:
        value = block.get(name)
        if not isinstance(value, str) or not value.strip():
            raise CheckError(
                f"'secrets.{name}' must be a secret reference such as "
                "'env://GITHUB_TOKEN' or 'aws-sm://team/token' — where the "
                "secret lives, never the secret itself")
        references[name] = value.strip()
    return references


# Inline-active Markdown punctuation: emphasis (*), code spans (`), links and the
# escape char itself ([ ] \). Escaping these neutralises the constructs that turn
# untrusted text into formatting or a link. Deliberately omitted: raw HTML and
# unsafe link schemes (already handled by the renderer — html-off, validated
# links, ADR-0018); ``_`` (literal between word characters in CommonMark, so
# ``MD0_DATA`` / ``debug_df_raw`` stay clean); and block markers (#, -, >) which
# are at worst cosmetic — keeping everyday text free of escape noise.
_MD_ESCAPE = {ord(ch): f"\\{ch}" for ch in "\\`*[]"}


def plain(text: object) -> str:
    """Escape inline Markdown so untrusted text — a path, an error, a captured
    line — renders **literally** in a reason (ADR-0018). Use it when folding
    external output into a reason; for multi-line / log output prefer
    :func:`code`."""
    return str(text).translate(_MD_ESCAPE)


def code(text: object) -> str:
    """Wrap captured output as a Markdown **code block** so it renders verbatim and
    inert (ADR-0018). The fence is longer than any backtick run in ``text``."""
    longest = run = 0
    for ch in str(text):
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def config_markdown(fields: dict[str, str | None]) -> str:
    """Render an allow-list of ``label -> value`` config fields as a Markdown
    bullet list (ADR-0013), in declaration order. Empty / ``None`` values are
    dropped, so a check can list optional fields without emitting blanks. The list
    shows as plain text until the Markdown renderer lands (`plan.md`)."""
    lines = [f"- **{label}:** {value}"
             for label, value in fields.items() if value]
    return "\n".join(lines)
