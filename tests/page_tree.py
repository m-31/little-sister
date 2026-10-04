"""A rendered page as a tree, and a stylesheet's rules by selector — for the tests
whose claim is about *where* something stands.

"Beneath its line", "framing every line" and "grouped under its node's path" are
statements about structure, and a substring cannot make one. This is enough of a
tree to ask them: elements with their classes and attributes, their order in the
document, what stands within what, and their text with or without what only a
screen reader is given. The templates close what they open, so nothing is inferred
the way a browser would.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input",
                   "link", "meta", "source", "track", "wbr"})


@dataclass(eq=False, repr=False)
class Element:
    """One element of a parsed page: enough of a tree to ask where things stand."""
    tag: str
    attrs: dict[str, str]
    parent: Element | None
    order: int
    children: list[Element | str] = field(default_factory=list)

    def __repr__(self) -> str:
        # a failing assertion prints this; the tree it hangs in would be the page
        named = "".join(f" {key}={value!r}" for key, value in self.attrs.items()
                        if key in ("id", "class"))
        return f"<{self.tag}{named}>"

    def has(self, name: str) -> bool:
        return name in self.attrs.get("class", "").split()

    def walk(self) -> Iterator[Element]:
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.walk()

    def all(self, name: str = "", tag: str = "") -> list[Element]:
        """Every descendant with the class ``name`` and the tag ``tag``, in the
        order the document writes them."""
        return [element for element in self.walk()
                if (not name or element.has(name))
                and (not tag or element.tag == tag)]

    def one(self, name: str = "", tag: str = "") -> Element:
        found = self.all(name, tag)
        assert len(found) == 1, f"{len(found)} of .{name} <{tag}>, wanted one"
        return found[0]

    def with_id(self, ident: str) -> Element:
        """The one element that carries ``ident`` as its id."""
        found = [element for element in self.walk()
                 if element.attrs.get("id") == ident]
        assert len(found) == 1, f"{len(found)} elements with id {ident!r}"
        return found[0]

    def first(self) -> Element:
        """The first element inside this one."""
        return next(child for child in self.children
                    if isinstance(child, Element))

    def within(self, other: Element) -> bool:
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False

    def source(self) -> str:
        """The text exactly as written — what a textarea holds."""
        return "".join(child for child in self.children if isinstance(child, str))

    def text(self, *, shown: bool = False) -> str:
        """The text on one line. ``shown`` leaves out what only a screen reader
        is given, so a mark's visible label and its name can be told apart."""
        parts: list[str] = []

        def gather(element: Element) -> None:
            for child in element.children:
                if isinstance(child, str):
                    parts.append(child)
                elif not (shown and child.has("visually-hidden")):
                    gather(child)

        gather(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    """The page as a tree. The templates close what they open, so an end tag
    closes the nearest open element of its name and nothing is inferred."""

    def __init__(self) -> None:
        super().__init__()
        self.root = Element("#document", {}, None, 0)
        self._open = self.root
        self._count = 0

    def handle_starttag(self, tag: str,
                        attrs: list[tuple[str, str | None]]) -> None:
        self._count += 1
        element = Element(tag, {name: value or "" for name, value in attrs},
                           self._open, self._count)
        self._open.children.append(element)
        if tag not in _VOID:
            self._open = element

    def handle_endtag(self, tag: str) -> None:
        node: Element | None = self._open
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._open = node.parent

    def handle_data(self, data: str) -> None:
        self._open.children.append(data)


def parse(html: str) -> Element:
    page = _Tree()
    page.feed(html)
    page.close()
    return page.root


def css_rule(css: str, selector: str) -> str:
    """The declarations of every rule that names exactly ``selector``, comments
    left out — empty where the sheet has no such rule."""
    sheet = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return "".join(
        body for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", sheet)
        if selector in (part.strip() for part in selectors.split(",")))


def css_rules_naming(css: str, part: str) -> list[str]:
    """The declarations of every rule whose selector mentions ``part``."""
    sheet = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [body for selectors, body in
            re.findall(r"([^{}]+)\{([^{}]*)\}", sheet) if part in selectors]
