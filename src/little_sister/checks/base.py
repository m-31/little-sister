"""Check abstraction: the base class, result type, config parsing and registry.

A check determines the status of one thing and returns a :class:`CheckResult`.
Subclasses register a ``type`` name; the loader instantiates them from YAML
(see ``loader.py``). Config fields common to every check: ``path``, ``name``,
``description``, ``frequency``, ``timeout`` (project.md §2.5), plus the
optional failure retry — ``retry_interval`` / ``retry_attempts`` (ADR-0033).
"""
from __future__ import annotations

import abc
import inspect
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from little_sister import secrets
from little_sister.errors import CheckError as CheckError
from little_sister.origins import release_of
from little_sister.reasons import (
    ReasonEntry,
    ReasonError,
    ReasonInput,
    derive_code,
    normalize,
)
from little_sister.status import StatusCode, join_path, leaf_name, split_path
from little_sister.values import number

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

    ``report`` is **what the run found**, as against ``config``'s what it ran
    *with* (ADR-0044): Markdown, written through on every run, shown on the
    node's page and never on a card. It is **never a status claim** — anything
    that should alarm is a reason, and this field must not become a second,
    quieter reason channel. What separates the two is status, not volume: a list
    whose items each carry a verdict is entries (capped on the card); a list
    whose items carry none is scope, and belongs here — the roster is presence,
    an entry is a claim. Unlike ``config``, whose root value comes from
    :meth:`Check.config_summary`, ``report`` rides the result on the root as on
    every child: it is an output of *this* run, so only the run can produce it.

    ``reason`` is **keyed** (ADR-0036): a check may hand over a plain string, a
    list of strings, a ``{slug: text}`` mapping, a list of ``(slug, text)``
    pairs or a list of :class:`~little_sister.reasons.Entry`, and
    ``__post_init__`` normalizes them all into ``reason_entries``.
    A mapping or a pairs list declares its entries **members** — individually
    suppressible, so an operator can pin the one finding they are working on; a
    sequence of strings needs ``entries=True`` to say the same, which exists so a
    check whose strings already carry identity (``f"{issue_id} {text}"``) gets
    per-entry pins without restructuring its return. Everything else is **prose**:
    keyed like all reasons, but one condition in several paragraphs, whose unit of
    suppression stays the node pin.

    **An entry may carry its own code** (ADR-0042), and then the *node's* code is
    derived rather than declared: hand over ``Entry(slug, text, code=…)`` lines
    and **omit ``code``** — declaring both is refused here, loudly, because a
    silently ignored code would be believed. The stored code is the worst of the
    entries' own codes (``UNDEFINED`` ignored; an **empty** entry set reads
    ``OK`` — the check ran, enumerated, and found nothing). ``Entry.running``
    marks a line whose subject has work in flight — display only, never severity.
    A result with prose, or with entries that all carry the node's code, keeps
    declaring ``code`` exactly as before; the engine's failure path is prose and
    is untouched (ADR-0040). ``stored_code`` is always the concrete code the
    engine upserts — declared or derived.

    ``about`` (subject metadata — what the node *is*) and ``title`` (a short
    display label) are the **type-inherent** labels a branch check gives the
    subnodes it emits (ADR-0025) — e.g. a metrics check captioning its ``disk`` /
    ``memory`` aspects. Like ``name`` they are **ignored on the root** (whose
    labels keep their ``nodes.yaml`` / inline-check sources), and unlike
    ``description`` / ``config`` they **fill an empty node field only**: a
    ``nodes.yaml`` declaration seeded at startup always wins, and the label
    freezes at its first fill (stable identity, not live status — text that
    changes with the observation belongs in ``reason``).

    ``order`` is a **declared rank** among a node's siblings (ADR-0055). Siblings
    render alphabetically, which destroys the one order a severity band set has:
    `wiz` puts ``informational`` between ``high`` and ``low``, and `github` puts
    ``low`` before ``medium``, which is a wrong statement about severity. A check
    that knows better says so — ``order=1`` pushes a child down, a negative value
    pulls one up — and the snapshot sorts by ``(order, name)``. **The default `0`
    is exactly today's behaviour**, so a check that never thought about order
    cannot accidentally publish its loop: the rank is declared, never incidental.

    Unlike ``name`` / ``about`` / ``title`` it is read on the **root as well as on
    children**, because a rank is not identity: ignoring it on the root would leave
    a check unable to rank the node it owns from its own code, which is half the
    point. It fills an unset field only, so both configured sources — a
    ``nodes.yaml`` ``order:`` and an inline ``order:`` on the check — still win.

    Where a check and a configuration file differ is what ``0`` means. A **check**
    writing ``0`` is saying nothing, because ``0`` is what saying nothing looks
    like; a configuration file naming ``order: 0`` has stated a rank, which is the
    only way a deployment can overrule what a check declared by naming the default
    value. **That is not the same as asking for alphabetical.** ``0`` is the rank
    the unranked carry, so a node at ``0`` sorts with them — after every negative
    rank, before every positive one. Zeroing one child of a set the check ranked
    ``1..5`` moves it to the **front**; handing that whole set back to the alphabet
    means stating ``order: 0`` on every sibling.
    """
    code: StatusCode | None = None
    reason: ReasonInput = field(default_factory=list)
    name: str = ""
    description: str = ""
    children: tuple[CheckResult, ...] = ()
    config: str = ""
    report: str = ""
    about: str = ""
    title: str = ""
    order: int = 0
    entries: bool = False
    #: Derived in :meth:`__post_init__` — the one internal form (ADR-0036).
    reason_entries: tuple[ReasonEntry, ...] = field(
        init=False, default=(), repr=False, compare=False)
    members: bool = field(init=False, default=False, repr=False, compare=False)
    #: The concrete code the engine stores — the declared ``code``, or the one
    #: derived from coded entries (ADR-0042). Always a ``StatusCode``.
    stored_code: StatusCode = field(
        init=False, default=StatusCode.UNDEFINED, repr=False, compare=False)

    def __post_init__(self) -> None:
        for child in self.children:
            if not child.name:
                raise CheckError("a child CheckResult must have a 'name'")
        # Normalize where the outside world enters (ADR-0026): five accepted input
        # forms, one internal one. A malformed slug is the check author's error and
        # surfaces as a failing check, not as a silent re-key.
        try:
            entries, members = normalize(self.reason, self.entries)
        except ReasonError as error:
            raise CheckError(str(error)) from error
        object.__setattr__(self, "reason_entries", entries)
        object.__setattr__(self, "members", members)
        # The ADR-0042 seam: a node with coded entries declares no code of its
        # own — every claim it makes is attributable to a line — and declaring
        # both is refused rather than silently resolved, the way a check YAML
        # naming `name:` is refused (ADR-0016).
        coded = any(entry.code is not None for entry in entries)
        if self.code is not None:
            if coded:
                raise CheckError(
                    "a result may declare a code or code its entries, never "
                    "both — a silently ignored code would be believed "
                    "(ADR-0042)")
            object.__setattr__(self, "stored_code", self.code)
            return
        if coded:
            object.__setattr__(self, "stored_code", derive_code(entries))
            return
        # No code and nothing to derive one from. The one legal shape is the
        # *entry-bearing empty set* — the check enumerated and found nothing,
        # said by an empty mapping or by `entries=True` beside an empty list —
        # which reads OK (ADR-0042: "nothing to report" is not "nothing
        # reported"). Anything else is a result that made claims with no
        # severity anywhere, and is the check author's error.
        if not entries and (self.entries or isinstance(self.reason, Mapping)):
            object.__setattr__(self, "stored_code", StatusCode.OK)
            return
        raise CheckError(
            "a result must declare a code, or hand over entries that carry "
            "their own (an empty entry-bearing set — an empty mapping, or "
            "entries=True beside an empty list — reads OK) (ADR-0042)")

    @property
    def reason_texts(self) -> list[str]:
        """The reason texts in the check's order, whatever form was handed over."""
        return [entry.text for entry in self.reason_entries]


CHECK_TYPES: dict[str, type[Check]] = {}

#: The **check API epoch** (ADR-0051). It bumps only when the check-authoring
#: surface of architecture.md §11 changes in a way a check type can notice — a name
#: removed or renamed, a documented behavior changed. Adding a name does not bump
#: it, and neither does anything else in a release: a plugin should not have to
#: follow the library's version, only the part of it that is its own contract.
API_VERSION = 1


def require_api(version: int, *, by: str = "") -> None:
    """Refuse at import unless this library speaks the check API ``version``.

    What a package built against a tag actually depends on is the *surface*, not
    the release — so it declares the epoch it was written for, from its
    ``__init__`` beside its `@register` imports, and a mismatch stops the process
    at startup with both numbers in the message instead of at the first run of one
    check, inside a name that moved.

    The install-time floor (``little-sister >= x`` in the package's metadata) is
    still the first line: it keeps a *too old* library from being installed at all.
    This is the second, for the upgrade the floor cannot see — a library that moved
    past the epoch the plugin was built for.

    ``by`` names the package in the message; the calling module's name is used when
    it is not given, which is right for the ordinary one-line call site.
    """
    if version == API_VERSION:
        return
    who = by or _calling_module()
    direction = ("newer than" if version > API_VERSION else "older than")
    raise CheckError(
        f"{who} was built for little-sister check API v{version}, which is "
        f"{direction} the v{API_VERSION} this little-sister ({_library_version()}) "
        f"speaks. Install a build of {who} for v{API_VERSION}, or a little-sister "
        f"that speaks v{version} (ADR-0051).")


def _calling_module() -> str:
    """The module that called into here — the package to name in a refusal."""
    frame = sys._getframe(2) if hasattr(sys, "_getframe") else None
    name = frame.f_globals.get("__name__", "") if frame is not None else ""
    return str(name) or "a dependent package"


def _library_version() -> str:
    """little-sister's own version, for a message. Imported late: ``little_sister``
    imports nothing from here, and this keeps it that way."""
    from little_sister import __version__
    return __version__


def register(type_name: str) -> Callable[[type[Check]], type[Check]]:
    """Class decorator registering a check under its ``type`` name.

    A name is claimed **once** (ADR-0051). Type names stay bare — `type: github`,
    not a namespaced spelling — so two packages can now claim one, and the registry
    has no answer: import order would pick the winner and every check of the losing
    package would silently run somebody else's code, against the losing package's
    configuration. So the second claim **refuses**, naming both classes.

    Re-registering the *same* class is not a conflict — a module re-imported under
    a reloading server re-runs its decorators, and refusing that would refuse the
    server.
    """
    def decorator(cls: type[Check]) -> type[Check]:
        claimed = CHECK_TYPES.get(type_name)
        if claimed is not None and not _same_class(claimed, cls):
            raise CheckError(
                f"two packages claim check type {type_name!r}: "
                f"{_where(claimed)} registered it and {_where(cls)} claims it too. "
                f"A type name answers for exactly one class — rename one of them, "
                f"or install only one of the packages (ADR-0051).")
        cls.type_name = type_name
        CHECK_TYPES[type_name] = cls
        return cls
    return decorator


def _same_class(claimed: type[Check], cls: type[Check]) -> bool:
    """Whether these are one class — by identity, or the same name in the same
    module, which is what a reload produces.

    The name match is deliberately restricted to **module-level** classes. A class
    built inside a function carries ``<locals>`` in its qualified name, and a factory
    called twice produces two genuinely different classes that share both names —
    accepting those as "a reload" would silently let the second overwrite the first,
    which is the whole failure this refusal exists to prevent.
    """
    if claimed is cls:
        return True
    if "." in cls.__qualname__ or "." in claimed.__qualname__:
        return False
    return ((claimed.__module__, claimed.__qualname__)
            == (cls.__module__, cls.__qualname__))


def _where(cls: type[Check]) -> str:
    """Where a check class comes from, for a refusal message."""
    return f"{cls.__module__}.{cls.__qualname__}"


@dataclass(frozen=True)
class TypeOrigin:
    """Where one registered check type came from — what ``/system`` shows.

    Once a type can arrive from a separately released package, "which code is
    answering for `type: github`, at which version" stops being derivable from this
    repository at all. An operator diagnosing a check has to be able to read it off
    the running instance, the way the slot fillers and the assembled policy already
    are (ADR-0051).
    """
    type_name: str
    module: str
    package: str
    distribution: str
    version: str
    #: Where the module was actually **loaded from**. The version beside it is the
    #: installed *metadata's* claim, and the two can disagree — a source copy on the
    #: path shadows an installed distribution of the same name, and the metadata
    #: keeps answering for code that is not running. That case is the one an
    #: operator comes to this page for, so the page shows both.
    path: str

    @property
    def builtin(self) -> bool:
        """Whether the library itself registered this type."""
        return self.package == "little_sister"


def registered_types() -> list[TypeOrigin]:
    """Every registered check type with its origin, by type name."""
    origins: list[TypeOrigin] = []
    for type_name, cls in sorted(CHECK_TYPES.items()):
        package = cls.__module__.split(".")[0]
        distribution, release = release_of(package)
        module = sys.modules.get(cls.__module__)
        origins.append(TypeOrigin(type_name=type_name, module=cls.__module__,
                                  package=package, distribution=distribution,
                                  version=release,
                                  path=getattr(module, "__file__", "") or ""))
    return origins


class Check(abc.ABC):
    """Base class for all checks.

    A check knows where it writes in the tree (``path``), how often it runs
    (``frequency_seconds``), how long to wait (``timeout_seconds``) and how to
    produce a result (:meth:`run`).
    """

    type_name: ClassVar[str] = ""

    def __init__(self, *, path: str, description: str = "",
                 about: str = "", title: str = "", order: int | None = None,
                 frequency_seconds: int = DEFAULT_FREQUENCY_SECONDS,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 retry_interval_seconds: int | None = None,
                 retry_attempts: int | None = None) -> None:
        # The check's full, absolute node path (ADR-0016); `name` is the last segment.
        self.path = join_path(path)
        self.description = description
        # Inline node metadata (nodes.yaml overrides each): `about` is subject
        # metadata (ADR-0012), `title` a short display label (ADR-0017), `order`
        # the node's rank among its siblings (ADR-0055). `order` is the one that
        # is `None` rather than empty when unstated, because `0` is a rank an
        # author may mean; the other two have no such value.
        self.about = about
        self.title = title
        self.order = order
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
        :func:`config_markdown`); the default is empty.

        Where it goes for a **branch** check depends on **who owns the container**
        (ADR-0044 decision 1), not on the check being a branch check: own that
        node alone and its whole-check text belongs there; **share** it with
        another check — the ``host-metrics`` + ``qnap-metrics`` shape — and this
        stays empty, with each child result's ``config`` tagged instead. A shared
        container withholds the text either way (two checks have no one answer,
        the rule that already withholds its timestamp and run facts), so a check
        with whole-check information to publish should own its own node. The same
        rule governs ``CheckResult.report``."""
        return ""

    def resolve_secret(self, reference: str) -> str:
        """Resolve a secret reference **at construction time** (ADR-0023).

        Every reference is ``scheme://address``: ``env://NAME`` reads that
        environment variable (``.env``, ADR-0003), and any other scheme goes
        through the resolver the application registered
        (``little_sister.secrets``). There is deliberately **no bare-name form** —
        a credential pasted where its reference belongs must fail the grammar
        rather than be looked up and echoed. Call this from
        ``__init__`` / ``_extra_from_config`` and keep the value — never
        resolve during :meth:`run` (cloud stores bill per read; rotation is a
        restart).

        A **malformed** reference raises :class:`CheckError`, so the load fails
        loudly like any config typo — an empty value, no ``scheme://`` at all, a
        scheme with no address, or a scheme no resolver is registered for. A
        well-formed reference
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
        """Build the check this config describes.

        The construction is guarded because the **common fields grow**. A check
        type written outside this repository is promised a list of *names*
        (ADR-0049), not a frozen constructor signature, so a type that spells the
        common keywords out instead of taking ``**kwargs`` stops binding the day
        one is added — which is what happened when ``order`` arrived (ADR-0055).
        Unguarded that surfaces as a bare ``TypeError`` from deep inside the
        loader, naming neither the file nor the type; a `CheckError` naming both
        is the difference between a five-minute fix and an afternoon.
        """
        common = _parse_common(config)
        extra = cls._extra_from_config(config, base_dir)
        try:
            return cls(**common, **extra)
        except TypeError as error:
            raise _construction_refused(cls, {**common, **extra}, error) from error

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        """Subclass hook: parse type-specific config into constructor kwargs."""
        return {}


def _construction_refused(cls: type[Check], kwargs: dict[str, Any],
                          error: TypeError) -> BaseException:
    """Turn a constructor that would not bind into a :class:`CheckError` naming
    the type and the keywords it refused — or hand the original error back
    untouched when it came from *inside* the constructor.

    That second case is the whole reason this is a function rather than three
    lines. A ``TypeError`` raised by the check's own body (``int(None)`` in an
    ``__init__``, say) is a real defect in that check, and relabelling it *"your
    constructor refuses a keyword"* would send its author looking in exactly the
    wrong place. The two are told apart by the traceback: a binding failure is
    raised by the call itself, so its traceback stops at this frame, while
    anything raised inside the callee has a frame below it.
    """
    if error.__traceback__ is not None and error.__traceback__.tb_next is not None:
        return error
    refused = _keywords_refused_by(cls, kwargs)
    if not refused:
        return error
    names = ", ".join(repr(key) for key in refused)
    return CheckError(
        f"check type {cls.type_name!r} ({cls.__module__}.{cls.__qualname__}) "
        f"does not accept {names}. The fields every check shares grow over time, "
        f"so a check type must take **kwargs and hand them to super().__init__() "
        f"rather than spelling them out — see the check-authoring surface "
        f"(ADR-0049)")


def _keywords_refused_by(cls: type[Check], kwargs: dict[str, Any]) -> list[str]:
    """Which of ``kwargs`` this constructor has no parameter for. Empty when it
    takes ``**kwargs`` (it refuses nothing) or when the signature cannot be read,
    in which case the caller keeps the original error rather than guessing."""
    try:
        parameters = inspect.signature(cls).parameters
    except (TypeError, ValueError):     # pragma: no cover - exotic callables only
        return []
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD
           for parameter in parameters.values()):
        return []
    return sorted(key for key in kwargs if key not in parameters)


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
        # A rank beside the labels it sits with (ADR-0055). Read only when the key
        # is *present*, so an absent one stays "nobody said" while a stated `0`
        # reaches the tree; a non-numeric one fails the load rather than being
        # dropped, because a silently ignored rank would leave the row in an order
        # nobody chose.
        "order": (number(config, "order", where="check config")
                  if config.get("order") is not None else None),
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
# untrusted text into formatting or a link. Linkification also recognizes a bare
# HTTP(S) scheme, so ``plain`` breaks that scheme token without changing its rendered
# text. Deliberately omitted: raw HTML and
# unsafe link schemes (already handled by the renderer — html-off, validated
# links, ADR-0018); ``_`` (literal between word characters in CommonMark, so
# ``MD0_DATA`` / ``debug_df_raw`` stay clean); and block markers (#, -, >) which
# are at worst cosmetic — keeping everyday text free of escape noise.
_MD_ESCAPE = {ord(ch): f"\\{ch}" for ch in "\\`*[]"}
_WEB_URL_SCHEME = re.compile(r"\bhttps?://", re.IGNORECASE)


def plain(text: object) -> str:
    """Escape inline Markdown so untrusted text — a path, an error, a captured
    line — renders **literally** in a reason (ADR-0018). Use it when folding
    external output into a reason; for multi-line / log output prefer
    :func:`code`."""
    escaped = str(text).translate(_MD_ESCAPE)
    return _WEB_URL_SCHEME.sub(
        lambda match: match.group().replace(":", r"\:"), escaped)


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
    dropped, so a check can list optional fields without emitting blanks. The
    result is rendered as Markdown (ADR-0018), so a value carrying Markdown
    punctuation is interpreted — fold it through :func:`plain` first where it is
    not operator-authored."""
    lines = [f"- **{label}:** {value}"
             for label, value in fields.items() if value]
    return "\n".join(lines)
