"""The declarative action list: `config/actions.yaml` (ADR-0038).

A **slot** (ADR-0034) lets a deployment put its own interaction on our pages, and
that seam is the right one when the interaction needs code — a provider that talks
to an API, a dialog that composes an issue before it posts. But the common case is
not that. The common case is *a link with the node's details in the query string*,
and asking for a Python package to express one is a tax on the ordinary.

So this is a filler the **library itself ships**, driven by configuration: an
operator writes label, icon and a URL template into `config/actions.yaml` and gets a
chip, with no deployment code at all. It was rejected as the *sole* seam — a
config-only list can never be more than a link — and is exactly right built on top
of one: the slot stays the general answer, and this is the shorthand for the case
that does not need it.

Two things it deliberately does not do. It does not invent a second placement rule:
an entry names which slot it fills, and the two slots already mean *about one
reason* and *about the whole node* (ADR-0036). And it does not template anything but
a URL — every substituted value is percent-encoded on the way in, so an action can
never be a way to get markup onto a page.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from little_sister import identity, self_report, slots, values
from little_sister.config_dir import aspect_files
from little_sister.logger import logger
from little_sister.reasons import plain, slug
from little_sister.status import HEARTBEAT_PATH
from little_sister.tags import spelled

#: The configuration aspect this reads — `config/actions.yaml`.
ACTIONS_ASPECT = "actions"

#: The slots an entry may name. The roster is the library's (ADR-0034); naming one
#: that is not in it is a typo, and the warning lists these.
PLACEMENTS = ("reason.actions", "node.actions")

#: What a URL template may interpolate, and where each comes from. Every value is
#: percent-encoded, so a reason full of quotes and ampersands lands in a query
#: string intact and can never become markup.
#:
#: ``reason`` is the one line for a per-reason action and the **first** line for a
#: node action — which is the node's summary, the rest being its body. A node action
#: also gets ``reasons``, every line joined by a newline, so "file a ticket about
#: this node" can carry the whole condition.
PLACEHOLDERS = ("path", "name", "code", "reason", "reasons")

_FIELD = re.compile(r"\{([a-z_]*)\}")


@dataclass(frozen=True)
class Action:
    """One configured action: a chip, and the URL it goes to."""
    label: str
    url: str
    slot: str
    icon: str = ""
    under: str = ""
    tag: str = ""

    def applies_to(self, path: str, tags: Collection[str] = ()) -> bool:
        """Whether this action is offered on the node at ``path``, which carries
        ``tags``.

        ``under`` is a **node path**, compared segment-wise, so ``/system/alpha``
        covers ``/system/alpha/disk`` and never ``/system/alphaville``. ``tag`` is a
        tag the node carries (ADR-0139 decision 7) — the selector vocabulary's other
        half, as a configured rule writes it — and where both are written both must
        hold.
        """
        if self.tag and self.tag not in tags:
            return False
        if not self.under:
            return True
        under = self.under if self.under.startswith("/") else "/" + self.under
        return path == under or path.startswith(under.rstrip("/") + "/")

    def href(self, *, path: str, name: str, code: str, reason: str,
             reasons: Sequence[str]) -> str:
        """The URL for one node (and, for a per-reason action, one reason)."""
        filled = {
            "path": path,
            "name": name,
            "code": code,
            "reason": reason,
            "reasons": "\n".join(reasons),
        }
        return _FIELD.sub(lambda m: quote(filled[m.group(1)], safe=""), self.url)


def load_actions(config_dir: str | Path | None = None) -> tuple[Action, ...]:
    """Read every root's `actions.yaml`, in path-list order.

    Layered like the checks rather than merged like the settings: an action is a
    whole thing, and a base root's actions plus a site root's actions is the reading
    an operator expects — the site *adds* its own, it does not have to restate the
    base's. A malformed entry is dropped with a warning naming the file and what was
    wrong; one bad entry never costs the others.
    """
    actions: list[Action] = []
    for layer in aspect_files(ACTIONS_ASPECT, config_dir):
        actions.extend(_read_layer(layer))
    return tuple(actions)


def _refused(path: Path, what: str, index: int | None = None) -> None:
    """An action file, or one action in it, that is not shown: a standing note,
    so the operator who wrote it learns it is missing without reading the log."""
    where = path if index is None else f"{path} action #{index + 1}"
    self_report.startup.note(
        slug("actions", path.name, "" if index is None else index + 1),
        plain(f"{where} {what}"))


def _read_layer(path: Path) -> list[Action]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        _refused(path, f"cannot be read ({error}); it is ignored")
        return []
    if data is None:
        return []
    if not isinstance(data, dict):
        _refused(path, "is not a mapping; it is ignored")
        return []
    raw = data.get("actions")
    if raw is None:
        _refused(path, "has no 'actions:' list; it is ignored")
        return []
    if not isinstance(raw, list):
        _refused(path, "'actions' is not a list; the file is ignored")
        return []
    found: list[Action] = []
    for index, entry in enumerate(raw):
        action = _read_entry(entry, path, index)
        if action is not None:
            found.append(action)
    return found


def _read_entry(entry: Any, path: Path, index: int) -> Action | None:
    """One entry, or ``None`` with a warning naming what was wrong."""
    where = f"{path} action #{index + 1}"
    if not isinstance(entry, dict):
        _refused(path, "is not a mapping; it is ignored", index)
        return None
    label = values.text(entry, "label").strip()
    url = values.text(entry, "url").strip()
    slot = values.text(entry, "slot").strip()
    if not label or not url:
        _refused(path, "needs both 'label' and 'url'; it is ignored", index)
        return None
    if slot not in PLACEMENTS:
        _refused(path, f"names the slot {slot!r} — an action fills one of "
                       f"{', '.join(PLACEMENTS)} (ADR-0038); it is ignored", index)
        return None
    unknown = sorted({field for field in _FIELD.findall(url)
                      if field not in PLACEHOLDERS})
    if unknown:
        # Refused at load rather than rendered broken: an action whose URL still
        # carries `{summary}` would silently send the operator somewhere useless.
        _refused(path, f"uses {', '.join('{' + field + '}' for field in unknown)} "
                       f"in its url — a template may interpolate "
                       f"{', '.join('{' + field + '}' for field in PLACEHOLDERS)} "
                       f"(ADR-0038); it is ignored", index)
        return None
    if slot == "node.actions" and "{reason}" in url and "{reasons}" not in url:
        logger.info(
            "actions: %s is a node action using {reason}, which is the node's "
            "first line only — {reasons} carries all of them", where)
    # The tag it is offered on (ADR-0139 decision 7): one tag, read as every tag is;
    # one that is no tag, or that the configuration writes for no node, picks nothing
    # for good — a lie about coverage, not a no-op — so the action is not shown.
    written = values.text(entry, "tag").strip()
    tag = spelled(written)
    if written and not tag:
        _refused(path, f"writes tag: {written}, which is no tag — one tag, lowercase "
                       f"letters and digits with hyphens between them; it is ignored",
                 index)
        return None
    if tag and _written_tags is not None and tag not in _written_tags:
        _refused(path, f"is offered on what carries {tag}, a tag the configuration "
                       f"writes for no node — a typo in the tag, or a tag no longer "
                       f"written; it is ignored", index)
        return None
    return Action(label=label, url=url, slot=slot,
                  icon=values.text(entry, "icon").strip(),
                  under=values.text(entry, "under").strip(), tag=tag)


#: Loaded once at startup and held for the process, like the check set: an action is
#: configuration, not status, and re-reading it per render would put a file read in
#: the ~10s poll.
_actions: tuple[Action, ...] | None = None

#: Every tag the configuration writes for a node (ADR-0139 decision 7), which an
#: action's ``tag:`` is held to — ``None`` until the start hands them over
#: (:func:`use_tags`), and then no action is refused for its tag.
_written_tags: frozenset[str] | None = None


def use_tags(written: Collection[str] | None) -> None:
    """Hold an action's ``tag:`` to the tags the configuration writes, once, at the
    start: an action offered on a tag no node is given is refused, the startup
    record saying why, as for any entry that cannot apply. ``None`` holds it to
    nothing, as before a start."""
    global _written_tags
    _written_tags = None if written is None else frozenset(written)
    forget_actions()


def current_actions(config_dir: str | Path | None = None) -> tuple[Action, ...]:
    """Every configured action, loading them on first use."""
    global _actions
    if _actions is None:
        _actions = load_actions(config_dir)
    return _actions


def forget_actions() -> None:
    """Drop the cache. For tests, and for a reload that does not exist yet."""
    global _actions
    _actions = None


def for_node(slot: str, path: str, tags: Collection[str] = ()) -> tuple[Action, ...]:
    """The actions that fill ``slot`` and apply to the node at ``path``, which
    carries ``tags``."""
    return tuple(action for action in current_actions()
                 if action.slot == slot and action.applies_to(path, tags))


# --- the library's own filler (ADR-0038) -------------------------------------
#
# The declarative list registers through the **slot seam** rather than beside it,
# so a configured chip and a deployment's coded one land in one rail in one order,
# `/system/installed` lists both, and there is a single render path to reason about.
# It is marked `builtin`, which is the one thing `slots.forget_fillers` puts back —
# the same posture the icon registry takes with its built-in pack.

#: The template both fillers use; the provider decides which chip class it wears.
FILLER_TEMPLATE = "_config_action.html"

#: The package the fillers resolve against — the library itself, reached through
#: exactly the loader an extension uses. `ext/little_sister/…` is additive like
#: every other extension name and cannot shadow a core template.
FILLER_PACKAGE = "little_sister"


def _entries(actions: Sequence[Action], *, path: str, name: str, code: str,
             reason: str, reasons: Sequence[str],
             icon_url: Any = None) -> list[dict[str, str]]:
    """The rendered values for a set of actions, hrefs already substituted."""
    built: list[dict[str, str]] = []
    for action in actions:
        built.append({
            "label": action.label,
            "href": action.href(path=path, name=name, code=code, reason=reason,
                                reasons=reasons),
            "title": f"{action.label} — {path}",
            "icon": icon_url(action.icon) if icon_url and action.icon else "",
        })
    return built


def reason_context(*, node: Any, reason: str, index: int,
                   surface: str) -> Mapping[str, object] | None:
    """Provider for `reason.actions`: the actions aimed at this node, for this line."""
    del index, surface
    actions = for_node("reason.actions", getattr(node, "path", ""),
                       getattr(node, "tags", ()))
    if not actions:
        return None
    entries = _entries(actions, path=getattr(node, "path", ""),
                       name=getattr(node, "name", ""),
                       code=getattr(getattr(node, "code", None), "name", ""),
                       reason=reason, reasons=[reason], icon_url=_icon_url)
    return {"actions": entries, "chip": "reason-action"}


def node_context(*, node: Any, surface: str) -> Mapping[str, object] | None:
    """Provider for `node.actions`: the actions aimed at this node, for the node.

    ``reason`` is the node's **first** line — its summary — and ``reasons`` is all
    of them, so a "file a ticket about this node" URL can carry the whole condition.
    """
    del surface
    actions = for_node("node.actions", getattr(node, "path", ""),
                       getattr(node, "tags", ()))
    if not actions:
        return None
    reasons = list(getattr(node, "reason", ()))
    entries = _entries(actions, path=getattr(node, "path", ""),
                       name=getattr(node, "name", ""),
                       code=getattr(getattr(node, "code", None), "name", ""),
                       reason=reasons[0] if reasons else "", reasons=reasons,
                       icon_url=_icon_url)
    return {"actions": entries, "chip": "node-action"}


def _icon_url(name: str) -> str:
    """An action's icon as a URL, or ``""`` when no rung of the search path defines
    the name — an ordinary answer, not an error, exactly as on the links page. The
    icon comes from the registry that already exists (ADR-0030 §3) rather than a
    second one: a deployment that dropped a mark in `config/links/icons/` can use it
    here by name, and the chip simply goes without when it cannot."""
    from flask import url_for

    from little_sister.links import current_links
    try:
        if current_links().icon_for(name) is None:
            return ""
        return url_for("link_icon", variant="on-light", name=name)
    except Exception:            # no request context, or an unreadable links aspect
        return ""


#: The template for the actions a package offers on its self-report node
#: (ADR-0076): buttons, because those are writes.
SELF_REPORT_TEMPLATE = "_self_report_actions.html"


def self_report_context(*, node: Any, surface: str) -> Mapping[str, object] | None:
    """Provider for `node.actions` on a child of ``/little-sister``: the actions a
    package registered for that contributor, for an admin, as POST forms."""
    del surface
    path = str(getattr(node, "path", ""))
    prefix = f"{HEARTBEAT_PATH}/"
    if not path.startswith(prefix) or "/" in path[len(prefix):]:
        return None
    contributor = path[len(prefix):]
    offered = self_report.actions_for(contributor)
    if not offered:
        return None
    from flask import url_for
    try:
        if not identity.signed_in().admin:
            return None
    except Exception:            # no request, or nobody behind the gate
        return None
    return {"actions": [{
        "label": action.label,
        "href": url_for("self_report_action", contributor=contributor,
                        slug=action.slug),
        "title": f"{action.label} — {path}",
    } for action in offered], "chip": "node-action"}


def register_builtin_fillers() -> None:
    """Register the library's own fillers. Idempotent."""
    slots.register("reason.actions", FILLER_PACKAGE, FILLER_TEMPLATE,
                   reason_context, builtin=True)
    slots.register("node.actions", FILLER_PACKAGE, FILLER_TEMPLATE,
                   node_context, builtin=True)
    slots.register("node.actions", FILLER_PACKAGE, SELF_REPORT_TEMPLATE,
                   self_report_context, builtin=True)
