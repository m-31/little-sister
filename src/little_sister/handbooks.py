"""A node's handbook: what a team writes at length about a node (ADR-0133 decision 3).

Its runbook, how to sign in, its policy, the reference a package ships — read on a tab
of its own, *Handbook*, where the node's *About* card holds the short account. A
handbook is a label as the ``about`` is, from the same sources in the same precedence
(ADR-0025, ADR-0012): ``nodes.yaml`` by path, over the check's own file — its own
node's ``handbook:`` and an aspect's under ``subnodes:`` — over what its type declares
and a run hands over.

**Text, or a file.** A statement that is a single line ending in ``.md`` names a
Markdown file; anything else is the text itself. A file is named where the handbook is
stated, relative to the directory it is stated against — the configuration directory a
check's file or a ``nodes.yaml`` belongs to, ``handbook: handbook/ec2.md`` beside
``checks/`` (ADR-0031), and a type's package for what the type declares — and never
found by a node's path: three accounts' ``ec2`` share one runbook, and a package knows
no deployment's paths. :func:`resolve` reads it where it is stated, so that what comes
after — ``{default}``, a type's tokens, the tree's fill — works on text alone.

**Read at a restart**, with the configuration, as ``nodes.yaml`` is: an edited runbook
reaches a running instance with the deployment that restarts it. What is wrong with a
statement goes on the startup record, where it stands until a restart: a file that is
missing or that lies outside the directory it is named against gives no handbook, and
a Markdown file in a configuration root's ``handbook/`` that nothing names is named
(:func:`note_unnamed`).

**A text links its own node's handbook by a short form** (ADR-0133 decision 4),
``handbook`` and ``handbook#<section>``, which the renderer leads there. One that leads
nowhere — to a section the handbook does not have, or on a node that has none — goes on
the startup record too (:func:`note_links`): at startup for the nodes whose handbook
the configuration alone gives, and for a node beneath a check's when a run first fills
it, its labels and its run's texts with it.
"""
from __future__ import annotations

import inspect
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import unquote

from little_sister import self_report
from little_sister.config_dir import aspect_in
from little_sister.errors import ConfigError
from little_sister.reasons import plain, slug
from little_sister.render import SHORT_FORM, anchors_of, short_links

#: The aspect of the configuration directory that holds a deployment's handbooks
#: (ADR-0031): a directory of Markdown files, named where a handbook is stated.
HANDBOOK_ASPECT = "handbook"
#: What makes a statement a file's name: one line ending in this.
FILE_SUFFIX = ".md"
#: How a detail is named among a node's texts on the startup record
#: (:func:`detail_texts`).
DETAIL = "detail"

_lock = threading.Lock()
#: Every file a statement named and read, resolved — what :func:`note_unnamed`
#: compares a ``handbook/`` directory against.
_named: set[Path] = set()


def names_a_file(stated: str) -> bool:
    """Whether a stated handbook names a file rather than being the text itself: a
    single line ending in ``.md``."""
    text = stated.strip()
    return bool(text) and "\n" not in text and text.lower().endswith(FILE_SUFFIX)


def resolve(stated: str, base: Path, *, where: str) -> str:
    """The handbook a statement gives: the text as written, or the text of the file
    it names, relative to ``base``.

    ``where`` says who stated it — *the check /web*, *config/nodes.yaml for '/a'*,
    *the run of /aws for /aws/ec2* — for the startup record's line, which names a
    file that is missing, that cannot be read, or that lies outside ``base``; each
    gives no handbook. A file read is remembered, for :func:`note_unnamed`."""
    if not names_a_file(stated):
        return stated
    named = stated.strip()
    root = base.resolve()
    path = (root / named).resolve()
    if not path.is_relative_to(root):
        _note(named, f"{where} names the handbook {named!r}, which lies outside "
                     f"{root}; it gives no handbook")
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _note(named, f"{where} names the handbook {named!r}, which is not in {root}; "
                     f"it gives no handbook")
        return ""
    except (OSError, UnicodeDecodeError) as error:
        _note(named, f"{where} names the handbook {named!r}, which cannot be read "
                     f"({error}); it gives no handbook")
        return ""
    with _lock:
        _named.add(path)
    return text


def configuration_directory(base_dir: Path) -> Path:
    """The configuration directory a check's file belongs to: the one holding the
    ``checks/`` directory the file was read from (ADR-0031), which is where a file it
    names is found."""
    return base_dir.parent


def package_directory(kind: type) -> Path:
    """The directory of the package a check type is defined in, which a file its
    declaration names is relative to."""
    try:
        return Path(inspect.getfile(kind)).resolve().parent
    except (TypeError, OSError):
        return Path.cwd()


def note_unnamed(roots: list[Path]) -> None:
    """Name each Markdown file in a configuration root's ``handbook/`` that no
    statement read (ADR-0133 decision 3): a runbook nobody's page shows.

    A root that holds the aspect in a form it does not have — a ``handbook.yaml`` —
    is named too, and not refused as the other aspects' are: a handbook is a node's
    metadata, which must not stop monitoring."""
    with _lock:
        named = set(_named)
    for root in roots:
        try:
            directory = aspect_in(root, HANDBOOK_ASPECT)
        except ConfigError as error:
            self_report.startup.note(slug("handbook", "aspect", str(root)),
                                     plain(str(error)))
            continue
        if directory is None:
            continue
        for path in sorted(directory.rglob(f"*{FILE_SUFFIX}")):
            if path.resolve() in named:
                continue
            shown = path.relative_to(root)
            self_report.startup.note(
                slug("handbook", "unnamed", str(path)),
                plain(f"{shown} in {root} is a handbook nothing names: no "
                      f"nodes.yaml entry, check file or subnodes: block states it"))


def detail_texts(details: Iterable[tuple[str, str]]) -> dict[str, str]:
    """The details given on a node (ADR-0133 decision 6) as texts of it for
    :func:`note_links`, each named by its key — ``detail 'contact'`` — since a link a
    detail writes in the short form leads into the handbook of the node it is given
    on."""
    return {f"{DETAIL} {key!r}": text for key, text in details}


def note_links(path: str, texts: Mapping[str, str], handbook: str) -> None:
    """Name each link the texts of the node at ``path`` write in the short form that
    leads nowhere (ADR-0133 decision 4): to a section its handbook does not have, its
    headings anchored as its page anchors them, or on a node that has none, whose
    link leads to a page that says no handbook is written. ``texts`` are the node's by
    what they are — its about, title, description and handbook, and its details
    (:func:`detail_texts`), a title and a detail read on one line as the page renders
    them — and ``handbook`` its handbook's text, ``""`` where it has none. One line
    for each text and target, standing until a restart."""
    # a link stands in a text as `](` or, defined, `]:`
    linked = [(field, section) for field, text in texts.items()
              if "](" in text or "]:" in text
              for section in short_links(
                  text, inline=field == "title" or field.startswith(f"{DETAIL} "))]
    if not linked:
        return
    sections = anchors_of(handbook) if handbook else frozenset()
    for field, section in linked:
        target = SHORT_FORM + section
        if not handbook:
            said = (f"the {field} of {path!r} links {target}, but no handbook is "
                    f"written for the node")
        elif section.strip("#") and unquote(section[1:]) not in sections:
            said = (f"the {field} of {path!r} links {target}, a section "
                    f"{'it' if field == 'handbook' else 'its handbook'} does not have")
        else:
            continue
        self_report.startup.note(slug("handbook", "link", path, field, target),
                                 plain(said))


def forget() -> None:
    """Drop what was named (tests)."""
    with _lock:
        _named.clear()


def _note(named: str, text: str) -> None:
    self_report.startup.note(slug("handbook", "stated", named), plain(text))
