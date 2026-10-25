"""The deployment's configuration directory: its roots, its aspects, and the shape
they must have (ADR-0031).

``LITTLE_SISTER_CONFIG_DIR`` is a **path-list** of configuration roots (default
``config``), so a deployment composes ``base:sites/alpha`` and stays DRY. The list
says **where** to look; each aspect says **how** its layers combine, because they
disagree for good reasons — checks union, settings merge per key, users do not merge
at all.

An **aspect** is one kind of configured thing. It is stored as
``config/<aspect>.yaml`` when one file can hold it and ``config/<aspect>/`` when it
cannot, and which forms are legal is a property of the aspect rather than of taste:
``checks`` is *always* a directory, because its unit of data is the file (one check
per ``*.yaml``, resolved against that file's own location) and there is no single
document to put in ``config/checks.yaml``. Both forms present in one root is an
error, not a precedence rule.

This module resolves paths and enforces that shape. It reads no YAML — each aspect's
loader does, applying its own rule: :func:`aspect_files` for the aspects that layer,
:func:`sole_aspect_file` for ``users``, which deliberately does not. It sits at the
bottom beside :mod:`little_sister.errors`, so ``config`` (settings) and the check
loader can both use it without either importing the other.

``.env`` and ``var/`` are **not** aspects and never will be: ``config/`` is
read-only input the operator authors, ``var/`` is state the program owns, and
``.env`` is secrets read before anything else (ADR-0003 / ADR-0014).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from little_sister import self_report
from little_sister.errors import ConfigError
from little_sister.logger import logger
from little_sister.origins import calling_package
from little_sister.reasons import plain, slug

CONFIG_DIR_ENV = "LITTLE_SISTER_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "config"

# What makes a directory entry a *candidate* aspect at all (point 3 of the ADR):
# a YAML file or a directory. Everything else — a README.md, a dotfile, an editor's
# .bak — is not a candidate and passes in silence, which matters because the library
# itself ships `config/checks/README.md` into that tree and a standing warning about
# a deployment's own documentation would train everyone to ignore the log.
YAML_SUFFIXES = (".yaml", ".yml")


@dataclass(frozen=True)
class Aspect:
    """One configurable aspect and the storage form(s) it may take."""
    name: str
    as_file: bool
    as_directory: bool

    def shape(self) -> str:
        """The legal form(s), phrased for an error message."""
        if self.as_file and self.as_directory:
            return f"config/{self.name}.yaml or config/{self.name}/"
        if self.as_directory:
            return f"config/{self.name}/"
        return f"config/{self.name}.yaml"


# The aspect names the **library** knows. Not discovered: an unrecognized candidate
# warns and is ignored rather than becoming a silent new aspect. An aspect joins this
# table when the loader that reads it lands, not before — a name known here but read
# by nobody would be worse than the honest "not a known aspect" warning.
#
# A dependent package adds its own with :func:`register_aspect` (ADR-0035), which is
# the registry seam this table's earlier note predicted; the built-ins below are the
# floor it cannot move.
BUILTIN_ASPECTS: dict[str, Aspect] = {
    # Always a directory — one check per file (see the module docstring).
    "checks": Aspect("checks", as_file=False, as_directory=True),
    # The declarative action list (ADR-0038). Layered like the checks rather than
    # merged: a site root *adds* its actions to a base root's.
    "actions": Aspect("actions", as_file=True, as_directory=False),
    # The configured rules at the contribution boundary (ADR-0137): one file, every
    # root's rules read as one list, the root named last first, since a later root
    # wins everywhere else in the chain. `little_sister.aggregation` is the loader.
    "aggregation": Aspect("aggregation", as_file=True, as_directory=False),
    # The deployment's last word on the Content-Security-Policy (ADR-0048 §5): the
    # sources it adds, and the one place a policy keyword may be taken at all.
    # Layered like the actions rather than merged — a policy is a union, so a site
    # root *adds* its sources and there is nothing to overwrite.
    # `little_sister.csp` is the loader.
    "csp": Aspect("csp", as_file=True, as_directory=False),
    # Both forms: one file until the deployment ships icon files of its own, a
    # directory holding `links.yaml` beside them once it does, so the aspect grows
    # without a second migration (ADR-0030). `little_sister.links` is the loader.
    "links": Aspect("links", as_file=True, as_directory=True),
    # Always a directory: the deployment's handbooks, one Markdown file each, named
    # where a node's handbook is stated (ADR-0133 decision 3) and never found by a
    # node's path. `little_sister.handbooks` is the loader.
    "handbook": Aspect("handbook", as_file=False, as_directory=True),
    "nodes": Aspect("nodes", as_file=True, as_directory=False),
    "settings": Aspect("settings", as_file=True, as_directory=False),
    # The known tags (ADR-0139 decision 3): one file, each tag with a line of what it
    # means, every root's read and added up, the later root's line winning for a tag
    # two of them name. It gives no node a tag. `little_sister.tags` is the loader.
    "tags": Aspect("tags", as_file=True, as_directory=False),
    # One file until the deployment adds per-user pictures; then `users.yaml`
    # moves inside the directory beside `avatars/` (ADR-0045).
    "users": Aspect("users", as_file=True, as_directory=True),
}

# Every aspect this process knows: the built-ins, plus whatever dependent packages
# have registered. One table, because the shape rule and the unknown-candidate
# warning must not care who declared a name.
ASPECTS: dict[str, Aspect] = dict(BUILTIN_ASPECTS)

# An aspect name is a bare directory/file stem — it is turned straight into a path
# under a configuration root, so it may not carry a separator, a dot or a `..`.
_ASPECT_NAME = re.compile(r"[a-z][a-z0-9_-]*")

# Which package registered each extension aspect, for `/system`. Separate from
# ASPECTS because the shape table is what the resolver reads and attribution is not
# its business; keyed by the same name, cleared with it.
_ASPECT_OWNERS: dict[str, str] = {}

# The pre-ADR-0031 layout, detected *only in order to refuse*. A deployment that
# upgrades without moving its files would otherwise come up looking alive while
# watching nothing, because a missing checks directory used to be survivable.
# Files only: `LITTLE_SISTER_CHECKS_DIR` is deliberately never read, not even as a
# hint (ADR-0031 §7) — one `os.environ` read would keep the retired name alive in
# the very code that removed it, and owe an answer to "set, but the tree is fine?".
_LEGACY_MARKERS: tuple[tuple[str, str], ...] = (
    ("checks", "checks/ -> config/checks/"),
    ("config.yaml", "config.yaml -> config/settings.yaml"),
    ("users.yaml", "users.yaml -> config/users.yaml"),
)


def register_aspect(name: str, *, as_file: bool = True,
                    as_directory: bool = False) -> None:
    """Declare a configuration aspect a dependent package reads (ADR-0035).

    A deployment extension that needs operator-editable settings of its own —
    an issue tracker's project id, say — puts them in ``config/<name>.yaml`` beside
    the library's aspects, rather than in a file of its own outside the tree the
    operator already knows. Registering the name is what makes that file a *declared*
    aspect instead of the "not a known configuration aspect" warning it would
    otherwise earn, and it buys the same shape enforcement, the same path-list
    layering (:func:`aspect_files`) and the same first-root-wins rule
    (:func:`sole_aspect_file`) the built-ins get.

    **Register before the app is imported** — in the same slot check types and icon
    packs use. The reason is the read, not a warning: :func:`aspect_in` looks the
    name up in ``ASPECTS``, so a package that resolves its own file before declaring
    it gets a :class:`KeyError` rather than a diagnosis, and the app resolves
    configuration during its own import. The report on files no aspect claims runs
    at the far **end** of that window (:func:`announce_aspects`, ADR-0070) rather
    than at the first resolution, so a registration made anywhere inside it is in
    time — which is what makes this rule followable by the package that turns out to
    be the first thing in the process to read a root.

    Every refusal is a warning and a skip, never an exception: the library's own
    aspects are the floor, and an extension may not move it — a registration that
    tries to redefine ``checks`` or ``users`` is dropped with both shapes named.

    **The registrant is recorded**, inferred from the calling package, so ``/system``
    can say whose ``config/<name>.yaml`` an operator is looking at. A name alone
    answers *is this file declared*; it does not answer *who reads it*, which is the
    question when the file is misbehaving and the answer is a package you did not
    write. Only the winning registration is attributed — a refused one owns nothing.
    """
    # Every refusal below is a standing note (ADR-0072 §7): a package's file that
    # is never read is a degradation the process cannot undo, and it names the
    # package that asked, which a log line alone left to whoever read it.
    who = calling_package() or "an unidentified package"
    if not _ASPECT_NAME.fullmatch(name):
        self_report.startup.note(
            slug("aspect", name),
            plain(f"{who} registers {name!r}, which is not a usable aspect name — "
                  f"an aspect is a bare lower-case stem under a configuration root "
                  f"(ADR-0035); its file is never read"))
        return
    if not as_file and not as_directory:
        self_report.startup.note(
            slug("aspect", name),
            plain(f"{who} registers the {name!r} aspect as neither a file nor a "
                  f"directory, so nothing could ever hold it — ignored (ADR-0035)"))
        return
    aspect = Aspect(name, as_file=as_file, as_directory=as_directory)
    if name in BUILTIN_ASPECTS:
        self_report.startup.note(
            slug("aspect", name),
            plain(f"{who} tries to redefine {name!r}, one of the library's own "
                  f"aspects ({BUILTIN_ASPECTS[name].shape()}), as {aspect.shape()} "
                  f"— the registration is ignored (ADR-0035)"))
        return
    existing = ASPECTS.get(name)
    if existing is not None and existing != aspect:
        self_report.startup.note(
            slug("aspect", name),
            plain(f"{who} registers the {name!r} aspect as {aspect.shape()}, but it "
                  f"is already registered as {existing.shape()}; the later one is "
                  f"ignored — the first registration wins (ADR-0035)"))
        return
    ASPECTS[name] = aspect
    _ASPECT_OWNERS[name] = calling_package()


def registered_aspects() -> tuple[str, ...]:
    """The aspect names a dependent package added, sorted — for ``/system``, so a
    registered aspect is visible from the running instance and not only from a log
    line at startup."""
    return tuple(sorted(set(ASPECTS) - set(BUILTIN_ASPECTS)))


def aspect_owner(name: str) -> str:
    """The package that registered ``name``, or ``""`` for a built-in (and for a
    registration made from a frameless interpreter, where the caller is unknowable —
    a missing attribution reads better on the page than a guessed one)."""
    return _ASPECT_OWNERS.get(name, "")


def forget_aspects() -> None:
    """Drop every registered aspect and put the library's own table back.

    For tests: an aspect one case registers must not decide another case's shape
    enforcement, its ``/system`` attribution or its unknown-candidate report.
    """
    ASPECTS.clear()
    ASPECTS.update(BUILTIN_ASPECTS)
    _ASPECT_OWNERS.clear()


def fatal(message: str) -> ConfigError:
    """Log a configuration failure at ERROR and return the exception to raise.

    ADR-0031 §7 promises each refusal names the resolved path it looked at **in the
    exception and in the log**. Nothing catches a :class:`ConfigError`, so without
    this the only record is whatever the WSGI server makes of the traceback — and an
    operator reading a service log should learn which directory was missing from one
    line, not by picking the message out of a stack trace.
    """
    logger.error("config: %s", message)
    return ConfigError(message)


def config_roots(spec: str | Path | None = None) -> list[Path]:
    """Resolve the configuration path-list into roots, in order.

    A :class:`~pathlib.Path` is a single root; a string is split on ``os.pathsep``
    (blank segments dropped); ``None`` reads ``LITTLE_SISTER_CONFIG_DIR`` and falls
    back to ``config``. **Every root must exist** — a named root that does not is a
    typo in a unit file, not an empty layer.

    Raises :class:`ConfigError` when a root is missing; when the default was used,
    the message also names the moves ADR-0031 asks for if the old layout is still
    lying around.
    """
    segments = _spec_segments(spec)
    defaulted = not segments
    roots = [Path(DEFAULT_CONFIG_DIR)] if defaulted else segments
    for root in roots:
        if not root.is_dir():
            raise fatal(_missing_root_message(root, defaulted))
    return roots


def aspect_files(name: str, spec: str | Path | None = None) -> list[Path]:
    """Every root's copy of the ``name`` aspect, in path-list order.

    The layering rule is the *caller's* — this returns the layers, it does not
    combine them. Roots that do not carry the aspect are simply absent from the
    list, which is normal: a site root holding only its own checks is the point.
    """
    found: list[Path] = []
    for root in config_roots(spec):
        path = aspect_in(root, name)
        if path is not None:
            found.append(path)
    return found


def sole_aspect_file(name: str, spec: str | Path | None = None) -> Path | None:
    """The **first** root's copy of the ``name`` aspect, or ``None``.

    The combining rule for ``users``: the first root that declares it wins
    *entirely* and a second is a warning, because merging identities across layers
    is a security question wearing a convenience costume. A deployment that wants
    that can ask for it later.
    """
    found = aspect_files(name, spec)
    if not found:
        return None
    if len(found) > 1:
        self_report.startup.note(
            slug("aspect", name, "roots"),
            plain(f"the {name!r} aspect is declared in {len(found)} roots; the first "
                  f"wins whole (ADR-0031) — using {found[0]}, ignoring "
                  f"{', '.join(str(path) for path in found[1:])}"))
    return found[0]


def aspect_in(root: Path, name: str) -> Path | None:
    """The path holding the ``name`` aspect inside one ``root``, or ``None``.

    Raises :class:`ConfigError` when the aspect is stored in a form it does not
    have (``config/checks.yaml``, ``config/settings/``) — the operator plainly meant
    that file, and quietly ignoring it would leave the instance watching less than
    was written — or when one root carries it **twice** (both forms, or both YAML
    suffixes), which is an error rather than a precedence rule so nobody has to
    reason about which one wins.
    """
    aspect = ASPECTS[name]
    directory = root / name
    files = [root / f"{name}{suffix}" for suffix in YAML_SUFFIXES]

    if directory.is_dir() and not aspect.as_directory:
        raise fatal(
            f"{directory} is a directory, but the {name!r} aspect is a single "
            f"file — use {aspect.shape()} (ADR-0031)")
    for path in files:
        if path.is_file() and not aspect.as_file:
            raise fatal(
                f"{path} is a file, but the {name!r} aspect is a directory — use "
                f"{aspect.shape()}, one entry per file (ADR-0031)")

    found: list[Path] = [directory] if directory.is_dir() else []
    found.extend(path for path in files if path.is_file())
    if len(found) > 1:
        raise fatal(
            f"the {name!r} aspect is present more than once in {root}: "
            f"{', '.join(str(path) for path in found)} — one form only, not a "
            f"precedence rule (ADR-0031)")
    return found[0] if found else None


def announce_aspects(spec: str | Path | None = None) -> None:
    """Report every configuration file no aspect claims — the startup line (ADR-0070).

    Called once, after the deployment's import-before-app block has run, for the same
    reason :func:`little_sister.identity.announce_doors` is: **that import is the
    moment the set of aspects is final**, and only then is a leftover file genuinely
    leftover. Emitted at the first *resolution* instead, as it was, the report named
    every aspect not yet registered at that instant — and since every registrar in
    this family declares its aspect and then immediately reads it, the first
    registration to run performed the scan and each one after it was reported as
    unknown for the life of the process. That made ADR-0035 §5's ordering rule
    unfollowable rather than merely delicate: a package cannot register above the
    call that scans when *being* a registration is what scans.

    Two things follow from the late position, and both are the point rather than a
    side effect. It covers **every configured root**, not only the roots something
    has happened to resolve, so a typo in a site root that carries nothing else is
    reported too. And the message can name the known aspects **with the packages that
    registered them**, which turns "this file is not an aspect" into a line an
    operator can act on: a misspelled ``identiy.yaml`` sits one character away from
    an ``identity`` whose reader the line now names.

    Anything may call it: a tool that reads one aspect and never builds an app gets
    the same report from the same line, and a process that genuinely has no final
    moment simply does not ask. Nothing here stops the monitor — an unrecognized
    candidate is ignored, exactly as before.
    """
    for root in config_roots(spec):
        _warn_unknown_candidates(root)


def _spec_segments(spec: str | Path | None) -> list[Path]:
    """The path-list's segments, or ``[]`` when nothing was given.

    The environment is read here rather than at import time, so a wrapper that sets
    the variable before importing the app (and a test that sets it per case) is
    honored.
    """
    if isinstance(spec, Path):
        return [spec]
    text = spec if spec is not None else os.environ.get(CONFIG_DIR_ENV, "")
    return [Path(segment) for segment in
            (raw.strip() for raw in text.split(os.pathsep)) if segment]


def _missing_root_message(root: Path, defaulted: bool) -> str:
    """The fatal message for a root that is not there, naming the resolved path —
    plus, when we fell back to the default, the moves that ADR-0031 asks for if the
    pre-ADR layout is still in the working directory."""
    where = (f"set {CONFIG_DIR_ENV}" if defaulted
             else f"named in {CONFIG_DIR_ENV}")
    message = (f"configuration directory not found: {root.resolve()} "
               f"({where}) — it holds this deployment's checks, nodes, settings "
               f"and users (ADR-0031)")
    if not defaulted:
        return message
    moves = [move for marker, move in _LEGACY_MARKERS if Path(marker).exists()]
    if moves:
        message += (". The layout moved: " + "; ".join(moves)
                    + " — move the files, they are not read where they are")
    return message


def _warn_unknown_candidates(root: Path) -> None:
    """Warn about the candidate aspects in one root that nobody has declared.

    Nothing here stops the monitor: an unrecognized candidate is ignored, and a
    non-candidate (README, dotfile, ``.bak``) passes in silence.
    """
    for entry in sorted(root.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            name = entry.name
        elif entry.suffix in YAML_SUFFIXES:
            name = entry.stem
        else:
            continue
        if name not in ASPECTS:
            self_report.startup.note(
                slug("ignored", name),
                plain(f"{entry} is not a known configuration aspect and is ignored "
                      f"(known: {_known_aspects()})"))


def _known_aspects() -> str:
    """The declared aspects, each registered one carrying the package that reads it.

    The attribution is the half worth having and it is only available late: a name
    alone says the file is not claimed, while ``identity (acme_sso)`` beside it says
    which package's document the operator meant to be editing, and therefore which one
    a near-miss spelling belongs to. A built-in is printed bare: this library reads
    it, which the reader already knows.
    """
    return ", ".join(
        f"{name} ({owner})" if (owner := aspect_owner(name)) else name
        for name in sorted(ASPECTS))
