"""The ``links`` aspect: a deployment's curated links, layered and re-read on change.

``/links`` is the shared toolbox around a failure — the Grafana everyone uses, the
ticket queue, the load-test console — and its content belongs to the deployment, not
to the library (ADR-0030). It arrives as the ``links`` aspect of the configuration
directory: ``config/links.yaml`` in each root of the path-list, or ``config/links/``
holding ``links.yaml`` beside icon files of the deployment's own (ADR-0031). Relative
paths inside the document resolve against **that document's own directory**, exactly
as they do inside a check config.

Three rules shape this module:

* **Groups merge by title, and order is never touched.** Same-titled groups across
  roots concatenate, base first, so a site root adds entries to a shared group. Entry
  order is curated — an operator who puts *EMERGENCY STOP* first means it.
* **Structural problems warn and continue** (ADR-0030 §8). A links page is a
  launcher, not the monitor: a typo in it must never take the instance down, so a bad
  entry is dropped, named in the log, and recorded in :attr:`LinksConfig.problems`.
  *Reachability* is a network question and lives nowhere near load time.
* **The file is re-read when it changes**, not loaded once — :func:`current_links`
  stats the layers per call and parses only when one moved. Status history is an
  in-memory ``deque`` (ADR-0001), so making an edit to a link cost a restart would
  cost the operator their incident history.

Icon *resolution* below the deployment's own rungs — the registered packs and the
built-in pack — is :mod:`little_sister.icons`'s; this module parses the deployment's
``icons:`` map and its ``icons/`` directory, and decides how an entry's mark is drawn
(:meth:`LinksConfig.mark_for`): from our own origin, from a remote mark's URL, or from
the entry's site favicon. The page's own Content-Security-Policy is taken from that
same answer (:meth:`LinksConfig.external_icon_urls`), so what the page loads and what
its policy allows cannot drift apart.
"""
from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from little_sister import csp, icons, values
from little_sister.config_dir import YAML_SUFFIXES, aspect_files
from little_sister.errors import CheckError
from little_sister.icons import Icon, IconFile
from little_sister.logger import logger

#: The aspect this module reads (ADR-0031). Both forms are legal: one file until the
#: deployment ships icon files of its own, a directory once it does.
LINKS_ASPECT = "links"

#: The document inside the directory form. Named for the aspect, so growing from
#: ``config/links.yaml`` into ``config/links/links.yaml`` is a move, not a rename.
LINKS_DOCUMENT = "links"

#: Where a deployment's own marks live inside the directory form:
#: ``config/links/icons/``. Files there are the deployment's own **pack**, resolved
#: by file name with no ``icons:`` entry — see :func:`_discover_icons`.
ICONS_DIRECTORY = "icons"

#: Schemes a link or a remote icon may use. Everything else — ``javascript:``,
#: ``data:``, ``file:`` — is dropped at load: these URLs end up in an ``href`` and an
#: ``img src`` on an operator's page.
ALLOWED_SCHEMES = ("http", "https")

#: Probe defaults (ADR-0030 §10). Icons are probed because a static asset fails
#: unambiguously; links are not, because a corporate ``403`` may mean three different
#: things. ``interval`` stays the raw duration string and is parsed where it is used,
#: the way :data:`little_sister.config.DEFAULT_MAINTENANCE_EXPIRY` is.
DEFAULT_PROBE_INTERVAL = "6h"
DEFAULT_ALIVE = (200, 301, 302, 401, 403)

_TOP_LEVEL_KEYS = ("groups", "icons", "check")
_GROUP_KEYS = ("title", "links")
_LINK_KEYS = ("title", "url", "icon", "note", "check")
_ICON_KEYS = ("on_light", "on_dark")
_PROBE_KEYS = ("icons", "links", "interval", "alive")

#: The value that turns a mark **off** rather than overriding it (ADR-0030 §3). YAML
#: decodes a bare ``none`` to ``None``, so both spellings arrive here as absence —
#: which is why an icon entry distinguishes "not declared" from "declared as none" by
#: the key being present at all.
_ICON_NONE = "none"


@dataclass(frozen=True)
class Link:
    """One curated entry: a title, a URL, an icon name, one line of Markdown.

    ``check`` is this entry opting **in** to reachability probing (off by default,
    ADR-0030 §10) — not to be read as the ``check`` of a monitored subject; nothing
    on this page reaches the status tree.
    """
    title: str
    url: str
    icon: str = ""
    note: str = ""
    check: bool = False


@dataclass(frozen=True)
class Group:
    """One flat category of links. Nesting is navigation, and the reader is
    mid-incident (ADR-0030), so there is exactly one level of these."""
    title: str
    links: tuple[Link, ...] = ()


@dataclass(frozen=True)
class ProbeSettings:
    """The top-level ``check:`` block — how reachability is probed, if at all.

    ``interval`` is kept as the raw duration string and parsed by the code that
    schedules the probe, so this module needs no duration parser (and no import of
    the ``checks`` package, which registers every check type as a side effect).
    """
    icons: bool = True
    links: bool = False
    interval: str = DEFAULT_PROBE_INTERVAL
    alive: tuple[int, ...] = DEFAULT_ALIVE


@dataclass(frozen=True)
class MarkImage:
    """One image an entry's mark is drawn with (ADR-0030 §3–4).

    ``variant`` is the background its file is for, ``on-light`` or ``on-dark``;
    ``side`` is the class that hides it under the other theme — ``light`` or ``dark``
    for a declared pair, empty for one image that serves both backgrounds. ``url`` is
    set where the viewer's browser fetches the image from elsewhere — a remote mark's
    own URL, or the entry's site favicon — and empty where the icon route serves it
    from our own origin, by the entry's ``icon:`` name.
    """
    variant: str
    side: str = ""
    url: str = ""


@dataclass(frozen=True)
class Mark:
    """How one entry's mark is drawn: its images, and whether they sit on the chip.

    ``bare`` is a declared pair with a file for each background, which has solved the
    theme itself; everything else — one file, a favicon — rides the page's
    theme-invariant light chip (ADR-0030 §4). An entry with nothing to draw has no
    image, and the page draws the neutral glyph.
    """
    images: tuple[MarkImage, ...] = ()
    bare: bool = False


def favicon_url(url: str) -> str:
    """The favicon of the site ``url`` is on — the rung of ADR-0030 §3 between the
    marks and the neutral glyph — or ``""`` where there is no host to ask, which the
    loader's scheme check already makes unreachable for a link that survived loading."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/favicon.ico" if parts.netloc else ""


@dataclass(frozen=True)
class LinksConfig:
    """Everything one load of the aspect produced, across every root.

    :attr:`problems` are the structural complaints in the order they were found —
    each also logged. They are carried on the record rather than only in the log
    because the audience for them is the person maintaining the file, and that
    person is looking at the page, not at a service log.
    """
    groups: tuple[Group, ...] = ()
    icons: Mapping[str, Icon] = field(default_factory=dict)
    probe: ProbeSettings = ProbeSettings()
    problems: tuple[str, ...] = ()
    sources: tuple[Path, ...] = ()

    def is_empty(self) -> bool:
        """No group carries an entry — the page has nothing to show."""
        return not any(group.links for group in self.groups)

    def icon_for(self, name: str) -> Icon | None:
        """The icon a link's ``icon:`` name resolves to, or ``None``.

        The first rungs of ADR-0030's search path, in order: **this deployment's own
        map**, then the files it dropped in ``config/links/icons/`` (both merged into
        :attr:`icons` at load, the map winning), then the packs registered by
        dependent packages, and the built-in pack under those
        (:func:`little_sister.icons.resolve` owns that half). ``None``
        means no rung defined the name — an ordinary answer, not an error: the page
        falls through to the entry's own favicon and then to a neutral glyph, which
        is how a mark we may not ship still costs a deployment nothing.
        """
        if not name:
            return None
        declared = self.icons.get(name)
        return declared if declared is not None else icons.resolve(name)

    def mark_for(self, link: Link) -> Mark:
        """How ``link``'s mark is drawn: which images, and where each one is from.

        The search path's last steps are decided here, per entry, because they depend
        on the entry and not on the name: a mark that resolved to nothing, or one
        turned off with ``none``, falls through to the site's own favicon, and a pair
        with a file for one background only takes the favicon for the other. A
        declared pair draws an image per background, and the page hides one by theme
        — under ``auto`` the server cannot know what the operating system resolves
        to; anything else draws one image, which serves both. A remote mark keeps its
        own URL: the route never proxies one, so the viewer's browser fetches it, as
        it fetches a favicon, and the page's own policy allows those hosts
        (:meth:`external_icon_urls`).
        """
        icon = self.icon_for(link.icon)
        live = icon if icon is not None and not icon.suppressed else None
        light = live.file_for("on-light") if live is not None else None
        dark = live.file_for("on-dark") if live is not None else None
        favicon = favicon_url(link.url)

        def image(file: IconFile | None, variant: str, side: str) -> MarkImage | None:
            if file is not None:
                return MarkImage(variant=variant, side=side, url=file.url)
            if not favicon:
                return None
            return MarkImage(variant=variant, side=side, url=favicon)

        drawn: tuple[MarkImage | None, ...]
        if live is not None and live.paired:
            drawn = (image(light, "on-light", "light"), image(dark, "on-dark", "dark"))
        else:
            drawn = (image(light, "on-light", ""),)
        return Mark(images=tuple(each for each in drawn if each is not None),
                    bare=bool(live is not None and live.paired and light and dark))

    def external_icon_urls(self) -> tuple[str, ...]:
        """Every URL the page sends a viewer's browser to for an icon, in page order,
        each once — the remote marks it draws and the favicons it falls back to.

        What the page's own Content-Security-Policy allows in ``img-src``, reduced to
        their origins (:func:`little_sister.csp.page_sources`). Those hosts are the
        page's to name: it exists to send the viewer to the sites it links to, so a
        browser that can open a link can fetch its icon, and the instance fetches
        none of them (ADR-0030). A mark from a pack or the deployment's own files is
        served from our own origin and is not here.
        """
        seen: dict[str, None] = {}
        for group in self.groups:
            for link in group.links:
                for drawn in self.mark_for(link).images:
                    if drawn.url:
                        seen.setdefault(drawn.url, None)
        return tuple(seen)


def links_policy_sources(config: LinksConfig) -> tuple[csp.Source, ...]:
    """What ``/links`` adds to its own ``img-src``: the origins its icons load from.

    Each is a host the file names — the site of an entry whose mark falls through to
    its favicon, the host of a remote mark — so the deployment writes it once, in
    ``links.yaml``, and the page's policy follows the file as it changes (ADR-0030,
    ADR-0048). Answerable to the file that names them, for ``/system/installed``.
    """
    by = ", ".join(str(path) for path in config.sources) or f"{LINKS_ASPECT}.yaml"
    return csp.page_sources(config.external_icon_urls(), by=by)


def load_links(config_dir: str | Path | None = None) -> LinksConfig:
    """Read the ``links`` aspect of every configuration root, in path-list order.

    The aspect is **optional**: no root need carry it, and a deployment that carries
    none gets an empty configuration rather than an error. Groups merge by title and
    concatenate base-first; the deployment's ``icons:`` entries resolve **per name**,
    a later root replacing an earlier one whole; the ``check:`` block merges per key.

    This always reads the files. :func:`current_links` is the caller a request
    should use — it stats first and reuses the last parse when nothing moved.
    """
    groups: list[Group] = []
    index: dict[str, int] = {}
    icon_map: dict[str, Icon] = {}
    icon_source: dict[str, Path] = {}
    probe = ProbeSettings()
    problems: list[str] = []
    sources: list[Path] = []

    for layer in aspect_files(LINKS_ASPECT, config_dir):
        document = _document_in(layer, problems)
        if document is None:
            continue
        sources.append(document)
        body = _read_document(document, problems)
        if body is None:
            continue
        _merge_groups(_parse_groups(body, document, problems),
                      groups, index, document, problems)
        # Within one layer, what the document **says** outranks what the directory
        # merely **holds**: an `icons:` entry is a statement (it may point at a URL,
        # or turn a name off with `none`), a discovered file is a convention.
        _merge_icons({**_discover_icons(layer, problems),
                      **_parse_icons(body, document, problems)},
                     icon_map, icon_source, document)
        probe = _parse_probe(body, document, probe, problems)

    _report_undefined_icons(groups, icon_map, problems)
    return LinksConfig(groups=tuple(groups), icons=icon_map, probe=probe,
                       problems=tuple(problems), sources=tuple(sources))


def current_links(config_dir: str | Path | None = None) -> LinksConfig:
    """The links configuration, re-read only when a layer actually changed.

    One ``stat()`` per layer per call, and a parse only when a size or modification
    time moved — or when a layer appeared, vanished, or the path-list itself is a
    different one from the last call. Editing a link must not cost a restart
    (ADR-0030 §7), and it must not cost a YAML parse per request either.
    """
    stamp = _stamp(config_dir)
    with _cache_lock:
        cached = _cache.get(stamp)
        if cached is not None:
            return cached
    loaded = load_links(config_dir)
    with _cache_lock:
        # One entry: a process serves one path-list, and a stale stamp is dead
        # weight the moment the file changes.
        _cache.clear()
        _cache[stamp] = loaded
    return loaded


def forget_cached_links() -> None:
    """Drop the parse cache, so the next :func:`current_links` reads from disk.

    Needed by tests, which rewrite a links file within the same second: the stamp
    below is (path, size, mtime), and a same-size rewrite inside one filesystem
    timestamp tick is exactly the case a test constructs and a human never does.
    """
    with _cache_lock:
        _cache.clear()


_cache_lock = threading.Lock()
_cache: dict[tuple[object, ...], LinksConfig] = {}


def _stamp(config_dir: str | Path | None) -> tuple[object, ...]:
    """A cheap fingerprint of the layers: their paths, sizes and mtimes, in order.

    A layer that is absent contributes its path and ``None``, so a file appearing or
    vanishing changes the stamp as surely as an edit does. The spec is part of the
    key because a test (and a wrapper) may resolve a different path-list.
    """
    marks: list[object] = [str(config_dir)]
    for layer in aspect_files(LINKS_ASPECT, config_dir):
        document = _document_in(layer, problems=None)
        if document is None:
            marks.append((str(layer), None))
            continue
        try:
            info = document.stat()
        except OSError:
            marks.append((str(document), None))
            continue
        marks.append((str(document), info.st_size, info.st_mtime_ns))
    return tuple(marks)


def _document_in(layer: Path, problems: list[str] | None) -> Path | None:
    """The YAML document for one layer: the file itself, or the one inside it.

    In the directory form the aspect's data sits beside its assets, so the document
    keeps the aspect's own name — ``config/links/links.yaml`` — and growing from the
    file form into the directory form is a move rather than a rename. Both suffixes
    present is an error rather than a precedence rule, for the reason ADR-0031 gives
    about the two aspect forms: nobody should have to reason about which wins.
    """
    if layer.is_file():
        return layer
    found = [layer / f"{LINKS_DOCUMENT}{suffix}" for suffix in YAML_SUFFIXES]
    present = [path for path in found if path.is_file()]
    if len(present) > 1:
        _complain(problems, f"{layer}: both {' and '.join(p.name for p in present)}"
                            f" are present — keep one")
        return None
    if not present:
        _complain(problems, f"{layer}: no {LINKS_DOCUMENT}{YAML_SUFFIXES[0]} in the "
                            f"links directory — the icons beside it have no document")
        return None
    return present[0]


def _read_document(document: Path, problems: list[str]) -> Mapping[str, object] | None:
    """Parse one layer's YAML into a mapping, or ``None`` when it is unusable.

    A broken links file costs this layer's entries and nothing else: the monitor
    keeps running and the page says what went wrong.
    """
    try:
        with open(document, encoding="utf-8") as handle:
            body = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        _complain(problems, f"{document}: unreadable ({error})")
        return None
    if body is None:
        return {}
    if not isinstance(body, Mapping):
        _complain(problems, f"{document}: top-level YAML must be a mapping, got "
                            f"{type(body).__name__}")
        return None
    _warn_unknown_keys(body, _TOP_LEVEL_KEYS, str(document), problems)
    return body


def _parse_groups(body: Mapping[str, object], document: Path,
                  problems: list[str]) -> list[Group]:
    """One document's groups, in file order, entries validated and dropped on sight
    of a problem. A group that survives with no entries is kept: the operator wrote
    the heading, and an empty category is visible feedback."""
    parsed: list[Group] = []
    for position, raw in enumerate(
            _sequence(body, "groups", str(document), problems), 1):
        where = f"{document}: groups[{position}]"
        if not isinstance(raw, Mapping):
            _complain(problems, f"{where}: expected a mapping, got "
                                f"{type(raw).__name__}")
            continue
        _warn_unknown_keys(raw, _GROUP_KEYS, where, problems)
        title = values.text(raw, "title").strip()
        if not title:
            _complain(problems, f"{where}: a group needs a title")
            continue
        links = _parse_links(raw, f"{document}: group {title!r}", problems)
        parsed.append(Group(title=title, links=links))
    return parsed


def _parse_links(raw: Mapping[str, object], where: str,
                 problems: list[str]) -> tuple[Link, ...]:
    """One group's entries, order preserved exactly as written."""
    links: list[Link] = []
    for position, entry in enumerate(_sequence(raw, "links", where, problems), 1):
        spot = f"{where}, links[{position}]"
        if not isinstance(entry, Mapping):
            _complain(problems, f"{spot}: expected a mapping, got "
                                f"{type(entry).__name__}")
            continue
        _warn_unknown_keys(entry, _LINK_KEYS, spot, problems)
        title = values.text(entry, "title").strip()
        url = values.text(entry, "url").strip()
        if not title or not url:
            _complain(problems, f"{spot}: an entry needs both a title and a url")
            continue
        if not _scheme_allowed(url):
            _complain(problems, f"{spot}: {title!r} has a url this page will not "
                                f"render ({url!r}) — use "
                                f"{' or '.join(ALLOWED_SCHEMES)}")
            continue
        links.append(Link(title=title, url=url,
                          icon=values.text(entry, "icon").strip(),
                          note=values.text(entry, "note").strip(),
                          check=values.flag(entry, "check")))
    _warn_duplicate_titles(links, where, problems)
    return tuple(links)


def _discover_icons(layer: Path, problems: list[str]) -> dict[str, Icon]:
    """The deployment's own pack: every icon file in ``<layer>/icons/``, by name.

    Dropping ``firewall.png`` in there and writing ``icon: firewall`` is the whole
    of it — no ``icons:`` entry, because the file already says its own name. That is
    what the ladder means by *a file the deployment authors* (ADR-0031 §8): the pack
    the deployment ships, discovered rather than declared, sitting above the packs a
    dependent package registers and below the map, which stays the way to say
    something a file cannot — a remote URL, or ``none``.

    The **pair convention is the built-in pack's own file names**:
    ``<name>-on-light.*`` and ``<name>-on-dark.*`` make one paired icon, anything
    else is a single file on the chip. One flat directory, no recursion.

    Only the **directory form** of the aspect has one of these, which is the point of
    that form (ADR-0031 §2): an ``icons/`` directory beside a flat
    ``config/links.yaml`` is a directory in a configuration root, and would be warned
    about as an unknown aspect rather than read as ours.
    """
    if not layer.is_dir():
        return {}
    directory = layer / ICONS_DIRECTORY
    if not directory.is_dir():
        return {}

    # name -> {"": single, "on_light": …, "on_dark": …}
    found: dict[str, dict[str, Path]] = {}
    for entry in sorted(directory.iterdir()):
        # Anything that is not an icon file passes in **silence** — a README, a
        # `.DS_Store`, an editor's backup. The same courtesy config_dir extends to a
        # non-candidate, and for the same reason: a standing warning about a
        # deployment's own housekeeping trains everyone to ignore the log.
        if not entry.is_file() or entry.suffix.lower() not in icons.ICON_TYPES:
            continue
        name, side = _split_variant(entry.stem)
        if not name:
            continue
        sides = found.setdefault(name, {})
        if side in sides:
            _complain(problems, f"{directory}: {sides[side].name} and {entry.name} "
                                f"both claim {name!r} — using {sides[side].name}")
            continue
        sides[side] = entry
    return {name: _discovered_icon(name, sides, directory, problems)
            for name, sides in found.items()}


def _split_variant(stem: str) -> tuple[str, str]:
    """A file's stem split into ``(name, side)`` — ``("aws", "on_light")`` for
    ``aws-on-light``, ``("aws", "")`` for ``aws``."""
    for marker, side in (("-on-light", "on_light"), ("-on-dark", "on_dark")):
        if stem.endswith(marker):
            return stem[: -len(marker)], side
    return stem, ""


def _discovered_icon(name: str, sides: dict[str, Path], directory: Path,
                     problems: list[str]) -> Icon:
    """One discovered name as an :class:`~little_sister.icons.Icon`."""
    single = sides.get("")
    on_light = sides.get("on_light")
    on_dark = sides.get("on_dark")
    if not (on_light or on_dark):
        # One file for both backgrounds, so it rides the theme-invariant chip.
        assert single is not None
        file = IconFile(path=single.resolve())
        return Icon(name=name, on_light=file, on_dark=file)
    if single is not None:
        _complain(problems, f"{directory}: {name!r} has both {single.name} and a "
                            f"light/dark pair — the pair wins, {single.name} is "
                            f"unused")
    if not (on_light and on_dark):
        _complain(problems, f"{directory}: {name!r} has only its "
                            f"{'on-dark' if on_light is None else 'on-light'} file; "
                            f"the other background falls through")
    return Icon(name=name, paired=True,
                on_light=IconFile(path=on_light.resolve()) if on_light else None,
                on_dark=IconFile(path=on_dark.resolve()) if on_dark else None)


def _parse_icons(body: Mapping[str, object], document: Path,
                 problems: list[str]) -> dict[str, Icon]:
    """One document's ``icons:`` map — the deployment's own rung of the search path.

    An entry is a single source, a mapping of the two backgrounds, or ``none``. A
    relative source resolves against the document's directory and may not leave it.
    """
    raw = body.get("icons")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        _complain(problems, f"{document}: 'icons' must be a mapping of name to "
                            f"file, got {type(raw).__name__}")
        return {}

    icons: dict[str, Icon] = {}
    for key, value in raw.items():
        name = str(key).strip()
        where = f"{document}: icons.{name}"
        if not name:
            _complain(problems, f"{document}: an icon needs a name")
            continue
        icon = _parse_icon(name, value, document, where, problems)
        if icon is not None:
            icons[name] = icon
    return icons


def _parse_icon(name: str, value: object, document: Path, where: str,
                problems: list[str]) -> Icon | None:
    """One ``icons:`` entry. ``None`` when it was too broken to keep."""
    if value is None or (isinstance(value, str) and value.strip() == _ICON_NONE):
        # `aws: none` — a mark deliberately not displayed. Without this a built-in
        # could be swapped but never turned off, which is the case a redistribution
        # question actually raises.
        return Icon(name=name, suppressed=True)

    if isinstance(value, Mapping):
        _warn_unknown_keys(value, _ICON_KEYS, where, problems)
        on_light = _icon_file(values.text(value, "on_light").strip(),
                              document, f"{where}.on_light", problems)
        on_dark = _icon_file(values.text(value, "on_dark").strip(),
                             document, f"{where}.on_dark", problems)
        if on_light is None and on_dark is None:
            _complain(problems, f"{where}: a pair needs on_light or on_dark")
            return None
        if on_light is None or on_dark is None:
            # A half pair is legal — an entry replaces a built-in **whole**, so a
            # deployment naming only one background deliberately leaves the other
            # to fall through rather than inheriting half of what it replaced.
            _complain(problems, f"{where}: only "
                                f"{'on_dark' if on_light is None else 'on_light'} "
                                f"is given; the other background falls through")
        return Icon(name=name, on_light=on_light, on_dark=on_dark, paired=True)

    source = _icon_file(str(value).strip(), document, where, problems)
    if source is None:
        return None
    # One file for both backgrounds: the page puts it on the theme-invariant chip,
    # which is the floor. A declared pair is the upgrade.
    return Icon(name=name, on_light=source, on_dark=source)


def _icon_file(source: str, document: Path, where: str,
               problems: list[str]) -> IconFile | None:
    """One icon variant: a remote URL, or a file beside the document.

    A local source must resolve **inside** the document's own directory. The route
    that serves these bytes takes its paths from here, so ``../../etc/passwd`` has
    to die at load rather than at request time.
    """
    if not source:
        return None
    if "://" in source:
        if not _scheme_allowed(source):
            _complain(problems, f"{where}: {source!r} is not a "
                                f"{' or '.join(ALLOWED_SCHEMES)} URL")
            return None
        return IconFile(url=source)

    base = document.parent.resolve()
    path = (base / source).resolve()
    if not path.is_relative_to(base):
        _complain(problems, f"{where}: {source!r} points outside "
                            f"{base} — an icon lives beside its configuration")
        return None
    if not path.is_file():
        # Offline and instant, so it belongs at load: a missing file is the failure
        # the reference page we looked at was showing as three broken-image glyphs.
        _complain(problems, f"{where}: {path} does not exist")
        return None
    if path.suffix.lower() not in icons.ICON_TYPES:
        # The route serves whatever this points at, so the type is decided here,
        # from an allowlist — not from whatever a content-type guess makes of it.
        _complain(problems, f"{where}: {path.name} is not an icon file type "
                            f"({', '.join(sorted(icons.ICON_TYPES))})")
        return None
    return IconFile(path=path)


def _parse_probe(body: Mapping[str, object], document: Path, inherited: ProbeSettings,
                 problems: list[str]) -> ProbeSettings:
    """The ``check:`` block, merged over the layers before it, per key.

    Same rule as ``settings`` (ADR-0031): the block is a flat mapping of scalars, so
    "later root wins per key" is well defined. A key a later root stays quiet about
    keeps the earlier root's value.
    """
    raw = body.get("check")
    if raw is None:
        return inherited
    if not isinstance(raw, Mapping):
        _complain(problems, f"{document}: 'check' must be a mapping, got "
                            f"{type(raw).__name__}")
        return inherited
    where = f"{document}: check"
    _warn_unknown_keys(raw, _PROBE_KEYS, where, problems)

    merged = replace(
        inherited,
        icons=values.flag(raw, "icons", default=inherited.icons),
        links=values.flag(raw, "links", default=inherited.links),
        interval=values.text(raw, "interval", default=inherited.interval).strip(),
    )
    if "alive" not in raw:
        return merged
    codes: list[int] = []
    for code in _sequence(raw, "alive", where, problems):
        try:
            codes.append(values.number({"code": code}, "code", where=where))
        except CheckError as error:
            _complain(problems, f"{where}.alive: {error}")
    return replace(merged, alive=tuple(codes))


def _merge_groups(parsed: list[Group], groups: list[Group], index: dict[str, int],
                  document: Path, problems: list[str]) -> None:
    """Fold one document's groups into the accumulated list, merging by title.

    Same-titled groups **concatenate**, base first — this deliberately differs from
    the checks loader, which hard-errors on overlap (ADR-0015): two checks claiming
    one node is an ambiguity about *truth*, two files contributing to one group is
    not. A new title is appended, so file order across the path-list decides layout.
    """
    for group in parsed:
        existing = index.get(group.title)
        if existing is None:
            index[group.title] = len(groups)
            groups.append(group)
            continue
        merged = groups[existing].links + group.links
        groups[existing] = replace(groups[existing], links=merged)
        logger.info("links: group %r extended by %s (ADR-0030)",
                    group.title, document)
        _warn_duplicate_titles(list(merged), f"group {group.title!r}", problems)


def _merge_icons(parsed: dict[str, Icon], icon_map: dict[str, Icon],
                 source: dict[str, Path], document: Path) -> None:
    """Fold one document's icon map into the accumulated one, **per name**.

    An entry replaces its name whole — no merging of ``on_light`` / ``on_dark``
    across layers, which is the rule that produces *"why is my light icon still the
    old one"*. Resolution being per name means a site root overriding ``aws`` leaves
    the other entries standing, and a shadowing is logged with winner and loser
    named, because a silent winner decided by root order is indistinguishable from a
    bug (ADR-0031 §8).
    """
    for name, icon in parsed.items():
        if name in icon_map:
            logger.info("links: icon %r from %s replaces the one from %s (ADR-0030)",
                        name, document, source[name])
        icon_map[name] = icon
        source[name] = document


def _report_undefined_icons(groups: list[Group], icon_map: dict[str, Icon],
                            problems: list[str]) -> None:
    """Name every ``icon:`` no rung of the search path defines.

    ADR-0030 §8 puts this among the structural checks — offline, instant — and it
    runs **after every layer is merged**, because a later root may be the one that
    defines the name. It is a report, not a rejection: an undefined name is legal
    and falls through to the entry's own favicon. Reported once per name however
    many entries use it, since the fix is one line either way.
    """
    undefined = {link.icon for group in groups for link in group.links
                 if link.icon and link.icon not in icon_map
                 and not icons.is_known(link.icon)}
    for name in sorted(undefined):
        _complain(problems, f"no icon named {name!r} — those entries fall back to "
                            f"their own site's favicon; define it under 'icons:'")
    if undefined:
        # The roster goes to the log, not onto the page: seventeen names turn the
        # page's problem block into four lines of prose nobody reads, and the
        # person who needs the list is the one already editing the file.
        logger.info("links: the names an icon pack defines are: %s",
                    ", ".join(icons.known_names()))


def _sequence(bag: Mapping[str, object], key: str, where: str,
              problems: list[str]) -> list[object]:
    """A list-valued key, or ``[]`` with a complaint when it is something else."""
    try:
        return list(values.rows(bag, key, where=where))
    except CheckError as error:
        _complain(problems, str(error))
        return []


def _scheme_allowed(url: str) -> bool:
    """Whether a URL uses a scheme this page will put in an ``href`` or an ``src``."""
    return urlsplit(url).scheme.lower() in ALLOWED_SCHEMES


def _warn_duplicate_titles(links: list[Link], where: str,
                           problems: list[str]) -> None:
    """Complain about a title appearing twice in one group — both are kept.

    Repetition inside a group is an editing mistake (a copy-paste, or two roots
    adding the same tool), but which of the two is wrong is the operator's call, not
    ours: dropping one would hide a URL somebody meant to change.
    """
    seen: set[str] = set()
    for link in links:
        if link.title in seen:
            _complain(problems, f"{where}: {link.title!r} appears more than once")
        seen.add(link.title)


def _warn_unknown_keys(bag: Mapping[str, object], known: tuple[str, ...], where: str,
                       problems: list[str]) -> None:
    """Complain about keys the loader does not read, naming the ones it does.

    A misspelled key is otherwise silent: the entry loads, the field is empty, and
    nothing says why.
    """
    unknown = [str(key) for key in bag if str(key) not in known]
    if unknown:
        _complain(problems, f"{where}: unknown key(s) {', '.join(sorted(unknown))} "
                            f"(known: {', '.join(known)})")


def _complain(problems: list[str] | None, message: str) -> None:
    """Record and log one structural problem. ``None`` means the caller is only
    stat-ing the layers and has no report to file."""
    if problems is None:
        return
    problems.append(message)
    logger.warning("links: %s", message)
