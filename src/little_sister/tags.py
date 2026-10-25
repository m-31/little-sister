"""A node's tags: the facts about it that do not follow the tree (ADR-0139).

A tag is a word a deployment writes for a node — ``production``, ``rack-4``,
``customer-facing`` — and it holds for the node and for every node beneath it. It is
a static fact about the subject, never one about its status, so nothing a run reads
gives or takes one (decision 1).

**Where a tag is written** (decision 2): in a check's file for the check's own node,
in its ``subnodes:`` block under an aspect's name, and in ``nodes.yaml`` by path —
wherever a deployment writes a node's details. A node carries every tag written for
it in any of them and every tag written for a node above it: a union everywhere, so
no source takes one back and a later configuration root adds to an earlier one's.

**The known tags** are the ``tags`` aspect, ``config/tags.yaml`` in each root
(decision 3): each tag with one line of what it means, every root's file read and
added up, the later root's line winning for a tag two of them name, each tag keeping
the place it was first named in. The wall's filter offers them in that order, and a
node lists its tags in it, the tags no file names after them by name.

**A tag is a word** (decision 3): lowercase letters and digits, hyphens between
them. Capitals are read as lower case, so ``Production`` is ``production``; anything
else is not read, and the startup record names where it is written. A tag no file
names still applies, and is named on the startup record once, with where it is
written — every tag, where no root has a file — since the file is where a tag says
what it means, and a second word for one thing is what it keeps out.

Nothing here stops the monitor: what cannot be read is a line on the startup record
(``self_report.startup``), never a refusal to start.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from little_sister import self_report
from little_sister.config_dir import aspect_files
from little_sister.reasons import plain, slug

#: The configuration aspect the known tags are read from.
ASPECT = "tags"

#: The tags one place of the configuration writes, or a node carries, in order.
Tags = tuple[str, ...]

#: A tag as it is read: lowercase letters and digits, words joined by one hyphen.
_SPELLING = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

#: How many of the places an unknown tag is written in its line names before it
#: counts the rest.
_PLACES_NAMED = 3


def spelled(word: str) -> str:
    """``word`` as a tag, capitals read as lower case — or ``""`` where it is none:
    the one rule every reader here and a selector's ``tag:`` share."""
    tag = word.strip().lower()
    return tag if _SPELLING.fullmatch(tag) else ""


def read(raw: object, where: str) -> Tags:
    """The tags one place of the configuration writes — ``tags:`` in a check's file,
    under an aspect's name in its ``subnodes:`` block, or in a ``nodes.yaml`` entry —
    in the order written, each once: a list of words, or one word alone. Absent or
    empty, it writes none.

    A word that is no tag is not read, and the startup record says so, naming
    ``where``: one with a character other than a letter, a digit or a hyphen, and a
    value YAML reads as anything but text — ``yes`` reads as true, ``0123`` as a
    number — which is no word the file says. The rest of the list stands."""
    if raw is None:
        return ()
    items: Sequence[object]
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list | tuple):
        items = raw
    else:
        _refused(where, "", f"{where} is a {type(raw).__name__}, where a tag or a "
                            f"list of tags is written; none of it is read")
        return ()
    found: dict[str, None] = {}
    for item in items:
        if not isinstance(item, str):
            _refused(where, str(item),
                     f"{where} names {item!r}, which YAML reads as a "
                     f"{type(item).__name__}; a tag is a word, so it is not read — "
                     f"put it in quotes")
            continue
        tag = spelled(item)
        if not tag:
            _refused(where, item,
                     f"{where} names {item!r}, which is not read: a tag is "
                     f"lowercase letters and digits, with hyphens between them")
            continue
        found[tag] = None
    return tuple(found)


def given(raw: Iterable[str] | None, where: str) -> Tags:
    """Tags handed over in code — a check built with them — read as a file's are, so
    that a check built in code keeps them as a file would."""
    if raw is None:
        return ()
    return read(list(raw), where)


def union(*groups: Iterable[str]) -> Tags:
    """Every tag of ``groups``, each once, in the order first met: how two places
    that write tags for one node add up, and a later root to an earlier one."""
    found: dict[str, None] = {}
    for group in groups:
        for tag in group:
            found[tag] = None
    return tuple(found)


@dataclass(frozen=True)
class Vocabulary:
    """The known tags (decision 3): each with the line that says what it means, in
    the order they were first named across the roots, and the files they came from —
    none where no root has a ``tags.yaml``."""

    lines: Mapping[str, str] = field(default_factory=dict)
    files: tuple[Path, ...] = ()

    def knows(self, tag: str) -> bool:
        """Whether a ``tags.yaml`` names ``tag``."""
        return tag in self.lines

    def line(self, tag: str) -> str:
        """What ``tag`` means, as its file says — empty where no file names it, or
        the file gives it no line."""
        return self.lines.get(tag, "")

    def ordered(self, tags: Iterable[str]) -> Tags:
        """``tags`` in the order a node lists them: the known ones in the files'
        order, then the rest by name."""
        rank = {tag: index for index, tag in enumerate(self.lines)}
        return tuple(sorted(set(tags), key=lambda tag: (
            (0, rank[tag], "") if tag in rank else (1, 0, tag))))


#: The vocabulary of a deployment that has none: every tag unknown.
NO_VOCABULARY = Vocabulary()


@dataclass(frozen=True)
class Chip:
    """One tag on a node's *About* card (decision 4): the tag, what it means, and
    ``at``, the node it is written on — the node itself, or the nearest above it that
    it comes down from — which the chip's tooltip names."""

    tag: str
    line: str
    at: str


def load_vocabulary(config_dir: str | Path | None = None) -> Vocabulary:
    """The known tags of every configuration root, in path-list order (ADR-0031):
    each root's ``tags.yaml`` read and added up, the later root's line winning for a
    tag two of them name and the tag keeping the place it was first named in.

    A file that is no mapping of tags to their lines is not read, and a tag in it
    that is no word, or whose line YAML reads as anything but text, is named — the
    startup record saying so, as for a tag a node is given — and a line written over
    several lines is one, its lines joined by a space, since a tooltip and an option
    show it on one."""
    lines: dict[str, str] = {}
    files: list[Path] = []
    for file in aspect_files(ASPECT, config_dir):
        files.append(file)
        try:
            with open(file, encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as error:
            _refused(str(file), "",
                     f"{file} is not read ({error}); the tags it names are unknown")
            continue
        if data is None:
            continue
        if not isinstance(data, Mapping):
            _refused(str(file), "",
                     f"{file} is not read: it maps each tag to a line that says what "
                     f"it means, and it is a {type(data).__name__}")
            continue
        for key, value in data.items():
            if not isinstance(key, str) or not spelled(key):
                _refused(str(file), str(key),
                         f"{file} names {key!r}, which is not read: a tag is "
                         f"lowercase letters and digits, with hyphens between them"
                         + ("" if isinstance(key, str) else
                            f" — YAML reads it as a {type(key).__name__}; put it in "
                            f"quotes"))
                continue
            tag = spelled(key)
            if value is None:
                lines[tag] = ""
            elif isinstance(value, str):
                lines[tag] = " ".join(part.strip()
                                      for part in value.strip().splitlines()
                                      if part.strip())
            else:
                _refused(str(file), tag,
                         f"{file} gives {tag!r} the line {value!r}, which YAML reads "
                         f"as a {type(value).__name__}; the tag is known and says "
                         f"nothing of what it means — put the line in quotes")
                lines[tag] = ""
    return Vocabulary(lines, tuple(files))


def note_unknown(vocabulary: Vocabulary,
                 places: Mapping[str, Sequence[str]]) -> None:
    """Name each tag the configuration writes that no ``tags.yaml`` names — every
    tag, where no root has one — once, with where it is written: ``places`` maps
    each tag to the places that write it, in the order met. The tag applies all the
    same; the line is the nudge to give it a meaning (decision 3)."""
    for tag in sorted(places):
        if vocabulary.knows(tag):
            continue
        written = list(dict.fromkeys(places[tag]))
        named = ", ".join(written[:_PLACES_NAMED])
        if len(written) > _PLACES_NAMED:
            named += f" and {len(written) - _PLACES_NAMED:,} more"
        if vocabulary.files:
            text = (f"the tag {tag!r}, written in {named}, is not among the known "
                    f"tags of {', '.join(str(file) for file in vocabulary.files)}; it "
                    f"applies, and the file is where a tag says what it means")
        else:
            text = (f"the tag {tag!r} is written in {named}, and no configuration "
                    f"root has a tags.yaml to say what it means; it applies")
        self_report.startup.note(slug("tags", "unknown", tag), plain(text))


def _refused(where: str, what: str, text: str) -> None:
    """A tag, or a file of them, that is not read: one standing line on the startup
    record, keyed by where it is written and what it says, so that the operator who
    wrote it learns it is missing without reading the log."""
    self_report.startup.note(slug("tags", "unread", where, what), plain(text))
