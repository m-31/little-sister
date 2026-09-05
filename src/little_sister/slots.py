"""Template slots: the declared places a dependent package may put its own HTML
(ADR-0034).

little-sister renders the frame; a deployment sometimes needs one **local
interaction** inside it — the house issue tracker, a runbook launcher, a link into
the deployment's own console. That interaction cannot live here (it knows a project
id and a custom field number that mean nothing to anyone else) and it cannot be
bolted on from outside either, because the surface it belongs on is a server-rendered
Jinja page that swaps under a ~10s poll.

A **slot** is the seam between the two. The library declares a named place in its
templates and the exact context it hands over there (:data:`SLOTS` is the whole
roster); a dependent package registers a **template of its own** for that name, plus
an optional **context provider** — a function that turns the slot's context into the
values its template needs. The split is the point: **data is computed in Python, HTML
is authored in Jinja**, rendered by little-sister's own environment with autoescaping
on. A deployment never builds an HTML string, so the untrusted halves of the context
(a reason line is assembled from captured output, ADR-0018) are escaped by the same
machinery that escapes them everywhere else.

Three properties keep the seam safe to upgrade into:

* **The roster is closed.** Registering for a name that is not in :data:`SLOTS`
  is refused with the known names logged. A slot is a promise the library keeps,
  so it has to be possible to see which promises exist.
* **Filling is additive, never shadowing.** Extension templates are reachable only
  as ``ext/<package>/<name>``, so no registration can replace a core template, and
  several packages may fill one slot — every filler renders, in registration order.
  (This deliberately differs from icon packs, where later registration *wins* per
  name: an icon is one mark and only one can be drawn, a slot is a *place things go*.)
* **A broken filler is contained.** A provider that raises or a template that
  will not render is logged with slot, package and template named, and that filler
  contributes nothing — the page still renders. Monitoring must not go dark because
  a button broke.

Registration lands in the same import-before-app slot ``CHECK_TYPES`` and the icon
packs already use — the deployment's WSGI wrapper, before ``little_sister.app`` is
imported — but nothing here depends on that: the loader and the renderer read the
registry at render time, so a late registration (a test's, for instance) is honored
too.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from inspect import Parameter, signature

from flask import render_template
from jinja2 import BaseLoader, Environment, PackageLoader, TemplateNotFound
from markupsafe import Markup

from little_sister import self_report
from little_sister.logger import logger
from little_sister.reasons import plain, slug

#: The directory an extension keeps its slot templates in, inside its own package.
TEMPLATE_DIR = "templates"

#: The directory an extension keeps its **static assets** in (ADR-0037) — the
#: sibling of :data:`TEMPLATE_DIR`, and the only place ``/ext/…`` will read from.
STATIC_DIR = "static"

#: What an extension may ship, and the mimetype each is served as. A short allowlist,
#: deliberately: these two are what a slot filler needs to look like part of the
#: product and to run a dialog, and every addition widens what an extension can put
#: into a page it does not own. No images — an icon already has a home (ADR-0030 §3),
#: and one seam per job.
#:
#: **Bare** mimetypes, no parameters: Flask appends the charset itself when a
#: response's mimetype is set, so a value carrying one here comes back doubled.
ASSET_TYPES: Mapping[str, str] = {
    ".css": "text/css",
    ".js": "text/javascript",
}

#: An asset is a **bare file name** inside the package's ``static/`` directory — no
#: separators, no ``..``. The same one rule that sandboxes an icon pack (ADR-0030
#: §3): an extension cannot name a path, so it cannot reach outside what it ships.
_ASSET_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

#: The prefix extension templates are mounted under. A name that does not start
#: with it is none of this loader's business, which is what keeps a registration
#: from being able to shadow a core template.
TEMPLATE_PREFIX = "ext"


@dataclass(frozen=True)
class Slot:
    """One declared place in the templates, and what is handed over there.

    ``context`` is the contract: exactly these names are passed to a filler's
    provider (as keyword arguments) and to its template. Adding a name to it is a
    compatible change; removing or renaming one is not, and belongs in a new ADR.
    """
    name: str
    context: tuple[str, ...]
    where: str


#: Every slot the library declares. Deliberately a short, closed roster — an
#: undeclared slot is a typo, not a new seam.
#:
#: The two differ in their **subject**, which is what decides where a deployment's
#: action belongs (ADR-0036): where a node's reasons are individually addressable
#: *members*, an action is about one of them and goes on the line; where they are
#: *prose* — a failure message and its stack trace are one condition in several
#: paragraphs — there is exactly one thing to act on and it is the node. A per-line
#: control there would offer to raise a ticket about a stack trace.
#:
#: Both are offered on **every** node regardless, because placement policy stays
#: with the filler: a provider returning ``None`` is how an extension declines a
#: node, a surface or a reason it has no action for.
#:
#: ``reason.actions`` hands over the line **twice**, and the pair is not
#: redundant: ``reason`` is its text, which is what a ticket's summary is made of
#: and what every filler written before this used; ``line`` is the whole
#: :class:`~little_sister.tree.ReasonLine` — its ``slug``, its own ``code``, its
#: ``running`` flag and whatever is pinned on it. Recovering that from ``index``
#: was possible and is exactly the mistake
#: [ADR-0036](../docs/adr/0036-addressable-reasons.md) decision 3 rejected by name:
#: an index moves when an entry is inserted above it, and a surface that ever
#: renders a filtered subset of reasons would silently point an action at a
#: different finding. A slug does not move, so the object carrying it is what the
#: slot promises.
SLOTS: Mapping[str, Slot] = {
    "reason.actions": Slot(
        name="reason.actions",
        context=("node", "reason", "line", "index", "surface"),
        where="beside one rendered reason line — every reason of every node, on "
              "the dashboard grid and on the leaf detail page",
    ),
    "node.actions": Slot(
        name="node.actions",
        context=("node", "surface"),
        where="on every node the dashboard grid draws as a box — a card head and "
              "each nested box under it — and beside the status on a leaf's own "
              "page; an action whose subject is the whole node",
    ),
}

#: A filler's optional context provider: it receives the slot's context as keyword
#: arguments and returns the extra names its template wants — or ``None`` to say
#: *nothing here*, which is how a filler declines a node, a surface or a reason it
#: has no action for. Returning ``None`` renders nothing at all, so an extension
#: expresses "leaves only" in Python rather than as an ``{% if %}`` wrapped around
#: its whole template.
ContextProvider = Callable[..., Mapping[str, object] | None]


@dataclass(frozen=True)
class Filler:
    """One package's contribution to one slot.

    ``builtin`` marks a filler the **library itself** ships — today the declarative
    action list (ADR-0038), which is configuration wearing the shape of an
    extension. It registers through this same seam so both kinds of chip land in one
    rail in one order, and it is the one thing :func:`forget_fillers` puts back, the
    way the icon registry keeps its built-in pack.
    """
    slot: str
    package: str
    template: str
    context: ContextProvider | None = None
    builtin: bool = False

    @property
    def source(self) -> str:
        """The template name this filler resolves to in the Jinja environment."""
        return f"{TEMPLATE_PREFIX}/{self.package}/{self.template}"


@dataclass(frozen=True)
class Asset:
    """One stylesheet or script a package ships for its fillers (ADR-0037).

    ``digest`` is a short content hash taken at registration. It is the
    cache-busting answer, and it is deliberately the **extension's** own answer:
    little-sister's version says nothing about whether this file changed, and the
    extension's release version says it only coarsely. The hash says exactly it.
    """
    package: str
    member: str
    digest: str

    @property
    def kind(self) -> str:
        """``css`` or ``js`` — which tag the library emits for this asset."""
        return self.member.rsplit(".", 1)[-1].lower()

    @property
    def content_type(self) -> str:
        return ASSET_TYPES["." + self.kind]


#: slot name -> the fillers registered for it, in registration order.
_registry: dict[str, list[Filler]] = {}

#: Every registered asset, in registration order — the order the tags are emitted
#: in, so a package that ships two stylesheets keeps its own cascade.
_assets: list[Asset] = []


def register(slot: str, package: str, template: str,
             context: ContextProvider | None = None,
             builtin: bool = False) -> None:
    """Fill ``slot`` with ``template`` from ``package``'s ``templates/`` directory.

    ``context`` is the optional provider described on :data:`ContextProvider`.

    Every refusal here is a **warning and a skip**, never an exception: a mistyped
    slot name or a template that did not ship must cost the deployment its button,
    not its monitoring. The warning names what was wrong and, for an unknown slot,
    every name that would have worked.
    """
    known = SLOTS.get(slot)
    if known is None:
        self_report.startup.note(
            slug("slot", package, slot, template),
            plain(f"{package} registers {template!r} for the unknown slot {slot!r} "
                  f"— known slots: {', '.join(sorted(SLOTS))} (ADR-0034); nothing "
                  f"of it is shown"))
        return
    if not _template_exists(package, template):
        self_report.startup.note(
            slug("slot", package, slot, template),
            plain(f"{package} names {template!r} for slot {known.name!r}, which is "
                  f"not in its {TEMPLATE_DIR}/ directory (ADR-0034); nothing of it "
                  f"is shown"))
        return
    filler = Filler(slot=known.name, package=package, template=template,
                    context=context, builtin=builtin)
    registered = _registry.setdefault(known.name, [])
    if any(other.source == filler.source for other in registered):
        logger.info("slots: %s already fills %r with %r — ignoring the repeat",
                    package, known.name, template)
        return
    registered.append(filler)
    logger.info("slots: %s fills %r with %r (%d filler(s) there now, ADR-0034)",
                package, known.name, template, len(registered))


def register_assets(package: str, *members: str) -> None:
    """Declare the stylesheets and scripts ``package`` ships for its fillers
    (ADR-0037).

    A slot filler could only ever render a link or a form: it may carry inline
    ``style=`` and a ``<form>``, but anything more — a dialog that composes an issue
    title before it posts — needs code, and there was no way to serve any. This is
    that way, kept narrow on purpose:

    * **The library emits the tag, never the extension.** A registered asset becomes
      a ``<link>`` or a deferred ``<script>`` in our own header, once per page, in
      registration order. An extension that wrote its own tag into a page it does not
      own would decide load order and caching for a document it cannot see.
    * **Served from our origin.** ``/ext/<package>/<member>``, read out of the
      package through :mod:`importlib.resources`. Never a third-party URL: same
      origin is what keeps a future ``script-src 'self'`` viable without a nonce for
      code the library never saw.
    * **A bare member name inside ``static/``**, exactly the icon pack's sandbox —
      no separators, no ``..``, and only ``.css`` / ``.js``.

    Every refusal is a warning and a skip, like every other registration here.
    """
    for member in members:
        asset = _accept_asset(package, member)
        if asset is None:
            continue
        if any(other.package == asset.package and other.member == asset.member
               for other in _assets):
            logger.info("slots: %s already ships %r — ignoring the repeat",
                        package, member)
            continue
        _assets.append(asset)
        logger.info("slots: %s ships %r as %s (ADR-0037)", package, member,
                    asset.kind)


def assets() -> tuple[Asset, ...]:
    """Every registered asset, in registration order."""
    return tuple(_assets)


def asset_for(package: str, member: str) -> Asset | None:
    """The registered asset ``package``/``member``, or ``None``.

    The route looks a request up here rather than building a path from it, so a
    member that walks out of the package does not exist to begin with — the same
    posture the icon route takes (ADR-0030 §3).
    """
    for asset in _assets:
        if asset.package == package and asset.member == member:
            return asset
    return None


def read_asset(asset: Asset) -> bytes:
    """The bytes of one registered asset.

    Raises :class:`OSError` when the file is gone — a package can be replaced under
    a running process, and a 404 is the honest answer then.
    """
    source = resources.files(asset.package).joinpath(STATIC_DIR, asset.member)
    return source.read_bytes()


def fillers(slot: str) -> tuple[Filler, ...]:
    """Everything registered for ``slot``, in registration order."""
    return tuple(_registry.get(slot, ()))


def all_fillers() -> tuple[Filler, ...]:
    """Every registration, slot by slot — for the ``/system`` page, so a filled
    slot is visible from the running instance and not only from the log. Includes
    the library's own built-in filler, which an operator reading that page has as
    much reason to see as a deployment's."""
    return tuple(filler for slot in sorted(_registry)
                 for filler in _registry[slot])


def extension_fillers() -> tuple[Filler, ...]:
    """Only what **dependent packages** added — :func:`all_fillers` minus the
    library's own. The distinction the seam is about: one of these is a promise
    little-sister keeps to somebody else's code."""
    return tuple(filler for filler in all_fillers() if not filler.builtin)


def packages() -> frozenset[str]:
    """The packages that have registered at least one usable filler."""
    return frozenset(filler.package for fillers_ in _registry.values()
                     for filler in fillers_)


def forget_fillers() -> None:
    """Drop every *extension* registration, keeping the library's own.

    For tests: a filler registered by one case must not decide another's render.
    A **built-in** filler is not a registration in that sense — it is part of the
    product, and dropping it would make the suite prove the absence of a feature
    every other run has. Same posture as the icon registry, which keeps its built-in
    pack across a reset.
    """
    for slot, registered in list(_registry.items()):
        kept = [filler for filler in registered if filler.builtin]
        if kept:
            _registry[slot] = kept
        else:
            del _registry[slot]
    _assets.clear()


def _accept_asset(package: str, member: str) -> Asset | None:
    """Validate one declared asset and hash it, or warn and return ``None``."""
    if not _ASSET_NAME.fullmatch(member):
        self_report.startup.note(
            slug("asset", package, member),
            plain(f"{package} names {member!r}, which is not a bare file name — an "
                  f"asset is one file inside the package's {STATIC_DIR}/ directory "
                  f"(ADR-0037); it is not served"))
        return None
    suffix = "." + member.rsplit(".", 1)[-1].lower() if "." in member else ""
    if suffix not in ASSET_TYPES:
        self_report.startup.note(
            slug("asset", package, member),
            plain(f"{package} names {member!r}, which is not a type we serve "
                  f"({', '.join(sorted(ASSET_TYPES))}) (ADR-0037); it is not "
                  f"served"))
        return None
    try:
        source = resources.files(package).joinpath(STATIC_DIR, member)
        payload = source.read_bytes()
    except (ModuleNotFoundError, TypeError):
        self_report.startup.note(
            slug("asset", package, member),
            plain(f"{package} is not an importable package, so {member!r} is not "
                  f"served (ADR-0037)"))
        return None
    except (OSError, ValueError):
        self_report.startup.note(
            slug("asset", package, member),
            plain(f"{package} names {member!r}, which is not in its {STATIC_DIR}/ "
                  f"directory (ADR-0037); it is not served"))
        return None
    digest = hashlib.sha256(payload).hexdigest()[:8]
    return Asset(package=package, member=member, digest=digest)


def render(slot: str, /, **context: object) -> Markup:
    """Render every filler of ``slot`` and concatenate the results.

    An unknown slot name raises — that is a bug in *our own* template, and the
    roster exists so it can be caught by a test rather than shrugged off at runtime.
    A failing *filler*, by contrast, is contained (see the module docstring).
    """
    if slot not in SLOTS:
        raise KeyError(
            f"unknown template slot {slot!r} — declared slots: "
            f"{', '.join(sorted(SLOTS))}")
    parts = [rendered for filler in _registry.get(slot, ())
             if (rendered := _render_one(filler, context))]
    return Markup("".join(parts))


class ExtensionLoader(BaseLoader):
    """Resolves ``ext/<package>/<template>`` against a **registered** package's
    ``templates/`` directory — and nothing else.

    Mounted behind the app's own loader (see ``little_sister.app``), so core
    templates are found first and an extension cannot reach a name outside the
    ``ext/`` prefix. Registration is read per lookup rather than captured at
    construction, so import order does not decide what is loadable.
    """

    def __init__(self) -> None:
        self._loaders: dict[str, PackageLoader] = {}

    def get_source(self, environment: Environment, template: str
                   ) -> tuple[str, str | None, Callable[[], bool] | None]:
        prefix, _, rest = template.partition("/")
        package, _, name = rest.partition("/")
        if prefix != TEMPLATE_PREFIX or not package or not name:
            raise TemplateNotFound(template)
        if package not in packages():
            raise TemplateNotFound(template)
        loader = self._loaders.get(package)
        if loader is None:
            try:
                loader = PackageLoader(package, TEMPLATE_DIR)
            except ValueError as error:  # no such package, or no templates/ dir
                raise TemplateNotFound(template) from error
            self._loaders[package] = loader
        return loader.get_source(environment, name)

    def list_templates(self) -> list[str]:
        """Every registered filler's template name — Jinja asks for this when a
        loader is introspected, and the honest answer is the roster we serve."""
        return sorted(filler.source for fillers_ in _registry.values()
                      for filler in fillers_)


def _accepted(provider: ContextProvider,
              context: Mapping[str, object]) -> dict[str, object]:
    """The part of ``context`` this provider is willing to receive.

    **A slot's context grows.** ``reason.actions`` gained ``line`` the day a
    control needed a line's slug rather than its text, and it will grow again;
    every provider that spelled its keywords out would break on each addition,
    with a logged failure and a silently missing chip — on a *published* seam,
    that is a deployment losing its buttons on an upgrade of ours. So a provider
    is handed exactly what it asks for: everything, if it declares ``**kwargs``,
    and otherwise the named parameters it has.

    This is the check-authoring surface's rule
    ([ADR-0049](../docs/adr/0049-the-check-authoring-surface.md)) reached
    by the other route. A check type must take ``**kwargs`` because the loader
    cannot know what a constructor wants; here the caller *can* look, so the
    burden is ours rather than the extension author's. A provider that wants the
    new value adds it and gets it; one written two releases ago keeps working
    untouched, which is the whole promise of a seam somebody else's code depends
    on.
    """
    try:
        parameters = signature(provider).parameters
    except (TypeError, ValueError):        # a callable with no readable signature
        return dict(context)
    if any(p.kind is Parameter.VAR_KEYWORD for p in parameters.values()):
        return dict(context)
    return {name: value for name, value in context.items() if name in parameters}


def _render_one(filler: Filler, context: Mapping[str, object]) -> str:
    """One filler's HTML, or ``""`` when it declines or breaks."""
    values = dict(context)
    if filler.context is not None:
        try:
            extra = filler.context(**_accepted(filler.context, context))
        except Exception as error:
            # Held, not standing: it happens per request and stops when the
            # package is fixed, so the line stands for the window and counts.
            logger.exception("slots: the context provider of %s for %r failed",
                             filler.package, filler.slot)
            self_report.runtime.see(
                slug("slot", filler.package, filler.slot),
                plain(f"the context provider of {filler.package} for "
                      f"{filler.slot!r} raised ({error!r}) — that filler renders "
                      f"nothing (ADR-0034)"), log=False)
            return ""
        if extra is None:
            return ""
        values.update(extra)
    try:
        return render_template(filler.source, **values)
    except Exception as error:
        logger.exception("slots: %s failed to render %r for %r", filler.package,
                         filler.template, filler.slot)
        self_report.runtime.see(
            slug("slot", filler.package, filler.slot),
            plain(f"{filler.package} failed to render {filler.template!r} for "
                  f"{filler.slot!r} ({error!r}) — that filler renders nothing "
                  f"(ADR-0034)"), log=False)
        return ""


def _template_exists(package: str, template: str) -> bool:
    """Whether ``package`` really ships ``templates/<template>``.

    Checked at registration so the log says *"that file is not there"* once at
    startup, instead of once per render behind a page that silently lost a button.
    Read through :mod:`importlib.resources`, so a zip import answers too.
    """
    try:
        root = resources.files(package)
    except (ModuleNotFoundError, TypeError):
        self_report.startup.note(
            slug("slot", package),
            plain(f"{package} is not an importable package, so nothing it "
                  f"registers for a slot is shown (ADR-0034)"))
        return False
    try:
        return root.joinpath(TEMPLATE_DIR, template).is_file()
    except (OSError, ValueError):
        return False


def slot_names() -> Iterable[str]:
    """Every declared slot name, sorted — for an error message or a doc test."""
    return sorted(SLOTS)
