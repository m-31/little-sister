"""The ``subnodes:`` block a check config may carry — read by the **library**.

A branch check's aspect leaves are **type-inherent** (ADR-0025), so their labels can
live **with the check** rather than be copy-pasted into ``nodes.yaml``. A deployment
retunes one in the check's own config: a ``subnodes:`` block, ``name -> {title,
about, handbook, show_when_quiet}``, in the same file the root's ``about`` / ``title``
live in. The same entry carries the aspect's ``details`` (ADR-0133 decision 6), which
are no label: :func:`parse_subnode_details` reads them as written, and they hold for
every node beneath the aspect.

**Every reader here is the library's own.** ``Check._parse_common`` runs
:func:`parse_subnodes` and :func:`parse_show_when_quiet` for every check whatever its
type, ``Check.__init__`` resolves the labels against what the type *declared*
(``subnode_defaults`` / ``label_tokens``) through :func:`resolve_text`, and the engine
applies both per child name. So a deployment can write this block for any installed
branch check with no check release, and a check type reads none of it — the flag since
ADR-0063, the labels since ADR-0025 decision 5, which is also when the three label
helpers left the check-authoring surface (they had no external caller left, and the
epoch moved with them, ADR-0051).

:func:`resolve_text` is the layering: the configured text when present, the type's
declared default otherwise, and a configured text may **extend** the default rather
than replace it by writing ``{default}`` into itself — which is what keeps text
inherent to the *type* in one place while a deployment still has the last word,
especially where one type runs several times (one check per team) and would otherwise
carry the same paragraphs in every instance's file. :func:`expand_tokens` lets that
text reuse a value the type declared (an ``org``, a severity legend) via ``{token}``
placeholders — a plain :func:`str.replace`, never ``str.format``, so backticks, braces
and other Markdown in the text stay intact.

**How a node first looks** rides the same block (ADR-0128): ``chips``, ``fold_ok`` and
``reason_cap`` per name, and under ``children:`` the same and the claim for each child
of the node, whatever its name — and so do a check's file's top level, a ``nodes.yaml``
entry and a type's declarations. :func:`read_stated` reads them out of any of those
mappings into a :class:`Stated`, :func:`parse_subnode_looks` out of the block, and
:func:`unknown_keys` names what one of them says that nothing reads, for the one line
each loader writes about it. Which statement wins is :mod:`little_sister.first_look`'s.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

from little_sister import details, tags, values
from little_sister.errors import CheckError

#: The first look's three keys (ADR-0128): whether a node's children start as chips,
#: whether its healthy lines and children start folded behind *✓ +N ok*, and its box's
#: line budget. ``true`` is the more compact look for both switches.
LOOK_KEYS = ("chips", "fold_ok", "reason_cap")
#: What a ``children:`` block says for each child of the node it stands under,
#: whatever the child's name: the first look's keys and the claim (ADR-0063).
CHILDREN_KEYS = (*LOOK_KEYS, "show_when_quiet")
#: What a type's ``subnode_defaults`` entry may say: the labels (ADR-0025) — the
#: ``handbook`` among them (ADR-0133) — the claim, the first look's keys and
#: ``children:``.
SUBNODE_KEYS = ("title", "about", "handbook", "show_when_quiet", *LOOK_KEYS,
                "children")
#: What a deployment's ``subnodes:`` entry may say: what a type's may, and the
#: aspect's ``details`` (ADR-0133 decision 6) and ``tags`` (ADR-0139 decision 2), which
#: a deployment gives and a type does not declare — a type gives its details through
#: its run, node by node, and gives no tag.
STATED_SUBNODE_KEYS = (*SUBNODE_KEYS[:3], "details", "tags", *SUBNODE_KEYS[3:])
#: What a type's ``node_defaults`` may say of its own node: the first look's keys and
#: ``children:``, since its labels and its claim are the check's file's.
NODE_DEFAULTS_KEYS = (*LOOK_KEYS, "children")


@dataclass(frozen=True)
class Stated:
    """What one place says of a node's **first look** (ADR-0128) — a check's file, its
    type, a ``nodes.yaml`` entry — each key ``None`` where the place says nothing, so
    the next place is free to speak and a stated ``false`` is a statement.

    ``chips`` is whether the node's children start as chips, ``fold_ok`` whether its
    healthy lines and children start folded behind *✓ +N ok*, ``reason_cap`` its
    box's line budget, and ``show_when_quiet`` the claim (ADR-0063) where the place
    says it here — a ``children:`` block, a subnode entry. ``children`` is the same
    for each child of the node whatever its name, which is how a look reaches a level
    a run names and that takes nothing declared for its names (ADR-0118); it holds no
    ``children`` of its own."""
    chips: bool | None = None
    fold_ok: bool | None = None
    reason_cap: int | None = None
    show_when_quiet: bool | None = None
    children: Stated | None = None

    def get(self, key: str) -> bool | int | None:
        """What this statement says of one of :data:`CHILDREN_KEYS`, or ``None``."""
        if key not in CHILDREN_KEYS:
            raise KeyError(key)
        said: bool | int | None = getattr(self, key)
        return said

    @property
    def says_anything(self) -> bool:
        """Whether any key is stated, here or in ``children``."""
        return (any(self.get(key) is not None for key in CHILDREN_KEYS)
                or (self.children is not None and self.children.says_anything))

    def over(self, base: Stated) -> Stated:
        """This statement per key, falling back to ``base`` where it is silent — a
        later configuration root's entry over an earlier one's (ADR-0031), its
        ``children`` merged the same way."""
        said = {item.name: (getattr(base, item.name) if getattr(self, item.name) is None
                            else getattr(self, item.name))
                for item in fields(self) if item.name != "children"}
        if self.children is None or base.children is None:
            kids = self.children if self.children is not None else base.children
        else:
            kids = self.children.over(base.children)
        return Stated(**said, children=kids)



@dataclass(frozen=True)
class Statements:
    """What one place — a check's file, or its type — says of the first look of the
    nodes the check writes: ``own`` for the check's own node, its ``children`` for
    each child of it, and ``by_name`` for every subnode of a name, at any depth
    (ADR-0128). The two places are kept apart because the file's ``children:``
    stands between the file's names and the type's (§3.4 of the interactive wall's
    note): the resolver asks them in that order."""
    own: Stated = field(default_factory=Stated)
    by_name: Mapping[str, Stated] = field(default_factory=dict)

def read_stated(bag: Mapping[str, Any], where: str, *, quiet: bool = False,
                children: bool = True) -> Stated:
    """The first look's keys out of one mapping — a check's file, a ``subnodes:``
    entry, a ``nodes.yaml`` entry, a type's declaration — read where they are stated
    and left ``None`` where they are not. ``quiet`` reads ``show_when_quiet`` too,
    for a place whose claim no other reader takes; ``children`` reads the
    ``children:`` block, which holds the same keys and the claim for each child.

    A switch must be a real boolean (:func:`~little_sister.values.strict_flag`) and
    ``reason_cap`` a whole number, 0 or more, or :class:`CheckError` names the key —
    ``bool("false")`` is ``True``, and a quoted ``"false"`` would close a level the
    file says to open."""
    kids: Stated | None = None
    if children and bag.get("children") is not None:
        raw = bag["children"]
        if not isinstance(raw, Mapping):
            raise CheckError(f"{where}.children must be a mapping of "
                             f"{' / '.join(CHILDREN_KEYS)}")
        kids = read_stated(raw, f"{where}.children", quiet=True, children=False)
    claim = _switch(bag, "show_when_quiet", where) if quiet else None
    return Stated(chips=_switch(bag, "chips", where),
                  fold_ok=_switch(bag, "fold_ok", where),
                  reason_cap=read_reason_cap(bag.get("reason_cap"), where),
                  show_when_quiet=claim, children=kids)


def read_reason_cap(value: object, where: str) -> int | None:
    """A box's line budget as a place states it: ``None`` where it is absent, else a
    whole number, 0 or more — ``reading_cap``'s shape beside it, so junk, a negative
    number and a boolean refuse the load."""
    if value is None:
        return None
    try:
        cap = int(str(value).strip())
    except ValueError as exc:
        raise CheckError(
            f"{where}.reason_cap: expected a whole number, got {value!r}") from exc
    if cap < 0:
        raise CheckError(f"{where}.reason_cap must be >= 0, got {value!r}")
    return cap


def _switch(bag: Mapping[str, Any], key: str, where: str) -> bool | None:
    """A tri-state switch: ``None`` where the key is absent, else a real boolean."""
    if bag.get(key) is None:
        return None
    return values.strict_flag(bag, key, where=where)


def unknown_keys(bag: Mapping[str, Any], known: tuple[str, ...],
                 where: str) -> list[str]:
    """The dotted names of the keys in ``bag`` that are not ``known`` — and of the
    keys of its ``children:`` block that are not :data:`CHILDREN_KEYS`, where
    ``known`` takes one — for the one startup line each loader writes about them."""
    found = [f"{where}.{key}" if where else str(key)
             for key in bag if str(key) not in known]
    raw = bag.get("children")
    if "children" in known and isinstance(raw, Mapping):
        found.extend(unknown_keys(raw, CHILDREN_KEYS,
                                  f"{where}.children" if where else "children"))
    return found


def parse_subnodes(config: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Parse a check config's optional ``subnodes:`` map — ``name -> {title, about,
    handbook}`` — into ``{name: {"title": …, "about": …, "handbook": …}}``, each as
    written: a ``handbook`` that names a file is read against the configuration
    directory by the check's construction (:mod:`little_sister.handbooks`). A missing
    block is ``{}``; a malformed one raises :class:`CheckError`, so a typo fails the
    load loudly.

    **The library is the caller**, like :func:`parse_show_when_quiet` beside it:
    ``Check._parse_common`` runs this for every type and ``Check.__init__``
    resolves what it returns over the type's declared defaults. A check that
    called it would be reading a block already read on its behalf, and would
    resolve a second, different answer for the same names."""
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, handbook, details, tags, show_when_quiet}")
    parsed: dict[str, dict[str, str]] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with "
                f"'title' / 'about' / 'handbook' / 'details' / 'tags' / "
                f"'show_when_quiet'")
        parsed[str(name)] = {"title": values.text(meta, "title"),
                             "about": values.text(meta, "about"),
                             "handbook": values.text(meta, "handbook")}
    return parsed


def parse_show_when_quiet(config: dict[str, Any]) -> dict[str, bool]:
    """Parse the ``show_when_quiet`` key out of the same ``subnodes:`` block
    :func:`parse_subnodes` reads — ``{name: True/False}``, and **only for the
    names that state it** (ADR-0063).

    **The library is the caller**, not the check: ``Check._parse_common`` runs
    this for every type and the engine applies the map per child name when a
    result is stored, over the shipped default the child result carries. That is
    deliberate — the key in a deployment's file is the *deployment's* statement,
    and a statement a deployment could only make through a check release would
    put the type in the deployment's lane. (The labels beside it were check-read
    at first, on the argument that layering them needs the type's own default
    text — which held only while that text was code a check applied. They joined
    this reader's side the moment it became a declaration: ADR-0025.) It is
    therefore **not** on the ``little_sister.checks`` facade — and since that
    record, neither is any other name here.

    A **second reader over one block**, rather than a third key in
    :func:`parse_subnodes`'s ``{title, about}`` mapping, and deliberately so. That
    mapping's values are strings, and everything downstream treats them as such —
    layering them through :func:`resolve_text`, scanning them for a ``{token}``. A
    boolean sitting among them would be a string everywhere but at the one call
    site that knew.

    Absence is the tri-state's third value and is carried by **absence from the
    result**: a name this returns nothing for said nothing, so the engine falls
    back to the child result's value — the type's shipped default — and a
    ``nodes.yaml`` declaration, seeded before the first tick, beats both. A
    present ``false`` is a statement and is returned as one. A non-boolean raises
    :class:`CheckError` — ``bool("false")`` is ``True``, so a quoted YAML boolean
    would switch the node on while the config says off.
    """
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, handbook, details, tags, show_when_quiet}")
    declared: dict[str, bool] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with "
                f"'title' / 'about' / 'handbook' / 'details' / 'tags' / "
                f"'show_when_quiet'")
        if meta.get("show_when_quiet") is None:
            continue
        declared[str(name)] = values.strict_flag(
            meta, "show_when_quiet", where=f"subnodes.{name}")
    return declared



def parse_subnode_looks(config: dict[str, Any]) -> dict[str, Stated]:
    """The first look's keys out of the same ``subnodes:`` block — ``{name: Stated}``,
    and **only for the names that state one** (ADR-0128). The claim beside them is
    :func:`parse_show_when_quiet`'s, so a :class:`Stated` here carries none of its
    own, but its ``children:`` block carries the claim for each child.

    The library is the caller, as for the two readers above: ``Check._parse_common``
    runs this for every type, and ``Check.__init__`` sets what it returns beside what
    the type declares, for the resolver (:mod:`little_sister.first_look`) and the
    engine to read in their order."""
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, handbook, details, tags, show_when_quiet}")
    looks: dict[str, Stated] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with "
                f"'title' / 'about' / 'handbook' / 'details' / 'tags' / "
                f"'show_when_quiet'")
        said = read_stated(meta, f"subnodes.{name}")
        if said.says_anything:
            looks[str(name)] = said
    return looks


def parse_subnode_details(config: dict[str, Any]) -> dict[str, details.Details]:
    """The ``details`` out of the same ``subnodes:`` block — ``{name: details}``, and
    **only for the names that state some** (ADR-0133 decision 6), each in the order
    written (:func:`little_sister.details.read`).

    They are the deployment's details for the aspect of that name, at any depth,
    which the engine writes on the child of that name as it writes each one — and,
    unlike a label, they are given down: they hold for every node beneath the aspect,
    a node a run names among them, which nothing declared for a name reaches
    (ADR-0118). So they are no label and are not resolved as one: no ``{default}``,
    since a type declares none for a name, and no token. The library is the caller,
    as for the readers above."""
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, handbook, details, tags, show_when_quiet}")
    stated: dict[str, details.Details] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            raise CheckError(
                f"subnodes.{name} must be a mapping with "
                f"'title' / 'about' / 'handbook' / 'details' / 'tags' / "
                f"'show_when_quiet'")
        if said := details.read(meta.get("details"), f"subnodes.{name}.details"):
            stated[str(name)] = said
    return stated


def parse_subnode_tags(config: dict[str, Any],
                       where: str = "") -> dict[str, tags.Tags]:
    """The ``tags`` out of the same ``subnodes:`` block — ``{name: tags}``, and only
    for the names that write some (ADR-0139 decision 2), each in the order written
    (:func:`little_sister.tags.read`); ``where`` names the file for the startup
    record, where a word that is no tag is named rather than read.

    They are the deployment's tags for the aspect of that name, at any depth, which
    the engine writes on the child of that name as it writes each one, as the
    aspect's details are — and like them they come down: they hold for every node
    beneath the aspect, a node a run names among them, which nothing declared for a
    name reaches (ADR-0118). The library is the caller, as for the readers above."""
    raw = config.get("subnodes") or {}
    if not isinstance(raw, dict):
        raise CheckError(
            "'subnodes' must be a mapping of leaf name -> "
            "{title, about, handbook, details, tags, show_when_quiet}")
    stated: dict[str, tags.Tags] = {}
    for name, meta in raw.items():
        if not isinstance(meta, dict):
            continue  # parse_subnode_details names it, and refuses the file
        prefix = f"{where}: " if where else ""
        if said := tags.read(meta.get("tags"), f"{prefix}subnodes.{name}.tags"):
            stated[str(name)] = said
    return stated


def unknown_check_keys(config: Mapping[str, Any]) -> list[str]:
    """What a check's file says the library does not read, of the keys the library
    owns: in a ``subnodes:`` entry, in a ``children:`` block under one, and in the
    top level's ``children:`` block. The rest of the top level is the type's, which
    the library cannot judge."""
    found: list[str] = []
    raw = config.get("children")
    if isinstance(raw, Mapping):
        found.extend(unknown_keys(raw, CHILDREN_KEYS, "children"))
    subnodes = config.get("subnodes")
    if isinstance(subnodes, Mapping):
        for name, meta in subnodes.items():
            if isinstance(meta, Mapping):
                found.extend(unknown_keys(meta, STATED_SUBNODE_KEYS,
                                          f"subnodes.{name}"))
    return found

def resolve_text(configured: str, default: str,
                 tokens: dict[str, str] | None = None) -> str:
    """One label's final text: the type's declared ``default``, what the
    deployment's ``subnodes:`` block says, or both. ``Check.__init__`` is the
    caller — once per name and field, at construction, which is what pins a
    ``{token}`` to a construction-time fact.

    An empty ``configured`` yields the default. Otherwise the config text wins —
    except that a ``{default}`` placeholder in it is replaced by the default, so a
    deployment can **extend** the shipped text (before it, after it, around it)
    instead of restating it. The substitution happens *before* :func:`expand_tokens`,
    so ``{token}`` placeholders inside the default text expand too; an aspect with no
    default resolves ``{default}`` to nothing rather than leaving the literal token
    on a dashboard.
    """
    text = configured if configured.strip() else default
    text = text.replace("{default}", default)
    return expand_tokens(text, tokens or {})


def expand_tokens(text: str, tokens: dict[str, str]) -> str:
    """Substitute ``{key}`` for each token via a plain replace (**not**
    ``str.format``), so backticks and stray braces in the Markdown are untouched.
    An unknown ``{token}`` is simply left as-is."""
    for key, value in tokens.items():
        text = text.replace("{" + key + "}", value)
    return text
