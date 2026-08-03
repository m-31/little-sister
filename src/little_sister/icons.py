"""Icon names, the packs that define them, and where an icon's bytes come from.

The links page refers to a mark **by name** — `icon: grafana`, never a URL — because
the same application appears many times on a real page and a dozen Grafana links
should cost one icon: one definition, one fetch, one probe (ADR-0030 §3). A name
resolves through a search path, first match wins, in the shape ADR-0021 already uses
for scripts:

1. the deployment's own ``icons:`` map — handled by :mod:`little_sister.links`,
   which owns the document those entries come from;
2. **icon packs registered by dependent packages**, later registration winning, so a
   house library of company-internal marks reaches every deployment that installs it;
3. **little-sister's built-in pack**, shipped as package data and served from our own
   origin, so the common case needs no configuration and makes no outbound request;
4. the link origin's ``/favicon.ico``, and finally a neutral glyph — both decided at
   render time by the page, because they depend on the *entry*, not on the name.

This module owns steps 2 and 3. It deliberately does **not** import
:mod:`little_sister.links`: names and files are one thing, the deployment's document
is another, and the dependency runs one way — ``links`` reads this, never the reverse.

**Resolution is per name, not per pack.** For each name independently the
highest-precedence pack that defines it wins, so a house pack defining only ``aws``
leaves the other sixteen built-ins standing, and an entry **replaces whole** rather
than filling in half of a pair. Registration lands in the same import-before-app slot
``CHECK_TYPES`` already uses, so import order can decide a winner — which is why a
shadowing is **logged with winner and loser named**. A silent winner decided by import
order is indistinguishable from a bug.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from little_sister.logger import logger

#: The built-in pack's package. Its own data directory, and nothing above it.
BUILTIN_PACKAGE = "little_sister.icon_pack"

#: The built-in roster (ADR-0030 §3): the DevOps marks nearly every deployment links
#: to. Deliberately fixed and short. Every one of them is **our own drawn glyph** —
#: a generic figure for what the product *does*, not the vendor's mark — which is what
#: lets the pack ship at all: no redistribution question, no trademark question, it
#: works offline, and it themes as a proper light/dark pair. The cost is
#: recognizability, and the answer to that is one line in a deployment's own ``icons:``
#: map pointing at the real mark. ``kibana`` and ``elastic`` are two names because
#: they are two marks. See the pack's ``manifest.yaml`` for what each one depicts.
BUILTIN_NAMES = (
    "grafana", "prometheus", "jenkins", "github", "gitlab", "kibana", "elastic",
    "jira", "confluence", "keycloak", "docker", "kubernetes", "argo", "sonar",
    "nexus", "pagerduty", "aws",
)

#: What an icon file may be. An `<img src>` on an operator's page, so the list is an
#: allowlist rather than "whatever the filesystem holds", and each entry names its own
#: content type instead of asking :mod:`mimetypes`, whose answer for ``.ico`` and
#: ``.svg`` varies by platform.
ICON_TYPES: Mapping[str, str] = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/vnd.microsoft.icon",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: A pack member is a **bare file name** inside the package's own data — no
#: separators, no ``..``. That one rule is the whole sandbox: a pack cannot name a
#: path, so it cannot reach outside the package data it ships.
_MEMBER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class IconFile:
    """Where one icon variant's bytes come from. Exactly one source is set.

    ``url`` is a remote file, emitted as its own URL and never proxied. ``path`` is a
    file the deployment authored, already checked to sit inside its configuration
    tree. ``package`` + ``member`` is a file inside a registered pack's package data,
    read through :mod:`importlib.resources` so it works from a zip import too.
    """
    url: str = ""
    path: Path | None = None
    package: str = ""
    member: str = ""

    @property
    def suffix(self) -> str:
        """The lower-cased file extension, for the content type."""
        name = self.member or (self.path.name if self.path else self.url)
        return Path(name).suffix.lower()


@dataclass(frozen=True)
class Icon:
    """One named mark, resolved to the file(s) that draw it.

    A brand logo does not theme — a black mark vanishes on the dark themes, a white
    one on the light — so an icon may name the file for each **background** it goes
    on. The keys are named for that background, not for the color of the file
    (ADR-0030 §4).

    A single-file icon sets both backgrounds to the same file and leaves
    :attr:`paired` false, which is what puts it on the page's theme-invariant light
    chip; a declared pair renders **bare**, having solved the problem itself. The chip
    is the floor, the pair is the upgrade. A :attr:`suppressed` icon is a name
    deliberately turned off (``aws: none``) — it falls through to the entry's own
    favicon, so a built-in can be switched off and not only swapped.
    """
    name: str
    on_light: IconFile | None = None
    on_dark: IconFile | None = None
    paired: bool = False
    suppressed: bool = False

    def file_for(self, variant: str) -> IconFile | None:
        """The file for ``on-light`` / ``on-dark``, or ``None`` when there is none."""
        return self.on_dark if variant == "on-dark" else self.on_light


#: name -> (icon, the package that registered it). One flat map, because resolution
#: is per name: the last pack to define a name owns it, and the packs that defined it
#: earlier keep every *other* name they brought.
_registry: dict[str, tuple[Icon, str]] = {}


def register_pack(package: str, names: Mapping[str, object]) -> None:
    """Register an icon pack: a package, and the files inside its data by name.

    Each value is a bare file name, or a mapping of ``on_light`` / ``on_dark`` file
    names. Call this **before importing the app**, in the same slot a deployment
    already registers its check types — and mind that the slot is import-order
    sensitive: keep the imports fenced (``# isort: off``) if a linter is allowed to
    reorder them.

    A name whose file is missing, badly named or of a type we will not serve is
    **skipped with a warning** rather than raising: one broken entry in a house pack
    must not stop a monitor from starting, and the warning names the file.
    """
    for raw_name, value in names.items():
        name = str(raw_name).strip()
        if not name:
            logger.warning("icons: %s registers an icon with no name", package)
            continue
        icon = _pack_icon(package, name, value)
        if icon is None:
            continue
        shadowed = _registry.get(name)
        if shadowed is not None and shadowed[1] != package:
            logger.info(
                "icons: %r from %s replaces the one from %s — later registration "
                "wins, per name (ADR-0030)", name, package, shadowed[1])
        _registry[name] = (icon, package)


def resolve(name: str) -> Icon | None:
    """The registered icon for ``name``, or ``None`` when no pack defines it.

    ``None`` is an ordinary answer, not an error: a name whose mark we may not ship
    still *exists* and simply falls through to the entry's own favicon.
    """
    found = _registry.get(name)
    return found[0] if found is not None else None


def is_known(name: str) -> bool:
    """Whether any registered pack defines ``name``."""
    return name in _registry


def known_names() -> tuple[str, ...]:
    """Every name a registered pack defines, sorted — for an error message."""
    return tuple(sorted(_registry))


def read_icon(file: IconFile) -> tuple[bytes, str]:
    """The bytes of one icon variant and its content type.

    Raises :class:`OSError` when the file is gone — a deployment may delete an icon
    while the process runs, and the page's own fallback is the right answer then.
    :class:`ValueError` for a type we do not serve, which the loaders reject long
    before this, so reaching it means something bypassed them.
    """
    content_type = ICON_TYPES.get(file.suffix)
    if content_type is None:
        raise ValueError(f"not an icon file type: {file.suffix!r}")
    if file.package:
        source = resources.files(file.package).joinpath(file.member)
        return source.read_bytes(), content_type
    if file.path is not None:
        return file.path.read_bytes(), content_type
    raise ValueError("a remote icon is emitted as its own URL, never read here")


def forget_packs() -> None:
    """Drop every registration and put the built-in pack back.

    For tests: a pack registered by one case must not decide another's resolution,
    and the built-in roster is the baseline every case starts from.
    """
    _registry.clear()
    register_builtin_pack()


def register_builtin_pack() -> None:
    """Register little-sister's own pack — the bottom rung of the search path.

    It goes in through the same door a dependent package uses, so the seam is the one
    that ships rather than a second path only outsiders take. Registering first is
    what makes it lose to everything else, which is the precedence the ADR asks for.
    """
    register_pack(BUILTIN_PACKAGE, {
        name: {"on_light": f"{name}-on-light.svg", "on_dark": f"{name}-on-dark.svg"}
        for name in BUILTIN_NAMES})


def _pack_icon(package: str, name: str, value: object) -> Icon | None:
    """One registration entry as an :class:`Icon`, or ``None`` when unusable."""
    if isinstance(value, Mapping):
        on_light = _pack_file(package, name, value.get("on_light"))
        on_dark = _pack_file(package, name, value.get("on_dark"))
        if on_light is None and on_dark is None:
            logger.warning("icons: %s defines %r with no usable file", package, name)
            return None
        return Icon(name=name, on_light=on_light, on_dark=on_dark, paired=True)
    single = _pack_file(package, name, value)
    if single is None:
        return None
    return Icon(name=name, on_light=single, on_dark=single)


def _pack_file(package: str, name: str, member: object) -> IconFile | None:
    """One member of a pack, checked to be a bare name, a servable type, and there."""
    if member is None:
        return None
    text = str(member).strip()
    if not _MEMBER.fullmatch(text):
        logger.warning(
            "icons: %s names %r for %r — a pack member is a bare file name inside "
            "its own package data, never a path", package, text, name)
        return None
    if Path(text).suffix.lower() not in ICON_TYPES:
        logger.warning("icons: %s names %r for %r, which is not an icon file type "
                       "(%s)", package, text, name, ", ".join(sorted(ICON_TYPES)))
        return None
    if not resources.files(package).joinpath(text).is_file():
        logger.warning("icons: %s names %r for %r, which is not in its package data",
                       package, text, name)
        return None
    return IconFile(package=package, member=text)


register_builtin_pack()
