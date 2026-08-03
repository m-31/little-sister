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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from little_sister import slots, values
from little_sister.config_dir import aspect_files
from little_sister.logger import logger

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

    def applies_to(self, path: str) -> bool:
        """Whether this action is offered on the node at ``path``.

        ``under`` is a **node path**, compared segment-wise, so ``/system/alpha``
        covers ``/system/alpha/disk`` and never ``/system/alphaville``. It is the
        half of the selector vocabulary that is already settled; a `tag:` selector
        waits for tags to exist, and an action written today keeps working when it
        arrives.
        """
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


def _read_layer(path: Path) -> list[Action]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        logger.warning("actions: cannot read %s: %s; ignoring", path, error)
        return []
    if data is None:
        return []
    if not isinstance(data, dict):
        logger.warning("actions: %s is not a mapping; ignoring", path)
        return []
    raw = data.get("actions")
    if raw is None:
        logger.warning("actions: %s has no 'actions:' list; ignoring", path)
        return []
    if not isinstance(raw, list):
        logger.warning("actions: %s: 'actions' is not a list; ignoring", path)
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
        logger.warning("actions: %s is not a mapping; ignoring", where)
        return None
    label = values.text(entry, "label").strip()
    url = values.text(entry, "url").strip()
    slot = values.text(entry, "slot").strip()
    if not label or not url:
        logger.warning("actions: %s needs both 'label' and 'url'; ignoring", where)
        return None
    if slot not in PLACEMENTS:
        logger.warning(
            "actions: %s names the slot %r — an action fills one of %s (ADR-0038); "
            "ignoring", where, slot, ", ".join(PLACEMENTS))
        return None
    unknown = sorted({field for field in _FIELD.findall(url)
                      if field not in PLACEHOLDERS})
    if unknown:
        # Refused at load rather than rendered broken: an action whose URL still
        # carries `{summary}` would silently send the operator somewhere useless.
        logger.warning(
            "actions: %s uses %s in its url — a template may interpolate %s "
            "(ADR-0038); ignoring", where,
            ", ".join("{" + field + "}" for field in unknown),
            ", ".join("{" + field + "}" for field in PLACEHOLDERS))
        return None
    if slot == "node.actions" and "{reason}" in url and "{reasons}" not in url:
        logger.info(
            "actions: %s is a node action using {reason}, which is the node's "
            "first line only — {reasons} carries all of them", where)
    return Action(label=label, url=url, slot=slot,
                  icon=values.text(entry, "icon").strip(),
                  under=values.text(entry, "under").strip())


#: Loaded once at startup and held for the process, like the check set: an action is
#: configuration, not status, and re-reading it per render would put a file read in
#: the ~10s poll.
_actions: tuple[Action, ...] | None = None


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


def for_node(slot: str, path: str) -> tuple[Action, ...]:
    """The actions that fill ``slot`` and apply to the node at ``path``."""
    return tuple(action for action in current_actions()
                 if action.slot == slot and action.applies_to(path))


# --- the library's own filler (ADR-0038) -------------------------------------
#
# The declarative list registers through the **slot seam** rather than beside it,
# so a configured chip and a deployment's coded one land in one rail in one order,
# `/system` lists both, and there is a single render path to reason about. It is
# marked `builtin`, which is the one thing `slots.forget_fillers` puts back — the
# same posture the icon registry takes with its built-in pack.

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
    actions = for_node("reason.actions", getattr(node, "path", ""))
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
    actions = for_node("node.actions", getattr(node, "path", ""))
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


def register_builtin_fillers() -> None:
    """Register the library's own filler for both slots. Idempotent."""
    slots.register("reason.actions", FILLER_PACKAGE, FILLER_TEMPLATE,
                   reason_context, builtin=True)
    slots.register("node.actions", FILLER_PACKAGE, FILLER_TEMPLATE,
                   node_context, builtin=True)
