import atexit
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from secrets import token_hex
from urllib.parse import parse_qs, urlencode, urlsplit

import yaml
from flask import (
    Flask,
    Response,
    abort,
    has_request_context,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue
from jinja2 import ChoiceLoader, StrictUndefined
from markupsafe import Markup

from little_sister import __version__, link_probe, slots, watch_lines
from little_sister.actions import register_builtin_fillers
from little_sister.api import authenticate, parse_api_tokens, problem, status_envelope
from little_sister.checks import CheckError, parse_duration
from little_sister.config import config
from little_sister.config_dir import (
    config_roots,
    registered_aspects,
    sole_aspect_file,
)
from little_sister.engine import Engine, create_engine
from little_sister.errors import ConfigError
from little_sister.icons import known_names, read_icon
from little_sister.links import LINKS_ASPECT, current_links
from little_sister.logger import logger
from little_sister.maintenance import MaintenanceEntry, MaintenanceStore
from little_sister.nodes import load_nodes, resolve_metadata, run_consistency_pass
from little_sister.render import render_markdown, render_markdown_inline
from little_sister.secrets import SecretError, resolve_setting
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusSnapshot, status_tree


def _load_dotenv(path: str = ".env") -> None:
    """Populate ``os.environ`` from a simple ``KEY=VALUE`` ``.env`` file.

    Dependency-free (see ADR-0003). Values already present in the environment
    take precedence; a missing file is fine.
    """
    try:
        with open(path, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(
                    key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()

app = Flask(import_name=__name__)
app.jinja_env.undefined = StrictUndefined
# Template slots (ADR-0034): a dependent package's own templates, reachable only as
# `ext/<package>/<name>` and only behind our own loader — so a registration adds a
# place's contents and can never replace one of our templates. Flask always installs
# a loader here; the guard is for the type, not for a case that happens.
_core_loader = app.jinja_env.loader
if _core_loader is not None:
    app.jinja_env.loader = ChoiceLoader([_core_loader, slots.ExtensionLoader()])

# How deep the /status tree renders before stopping (the default and the ceiling
# for the user-chosen depth).
MAX_DEPTH = 8
# Remember a viewer's chosen view (depth + the on/off switches) for a year.
VIEW_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Presentation preferences (ADR-0029): how this browser wants the surface to
# look. One cookie holds them, urlencoded so a later key can join without a
# migration, and it is read server-side into body attributes so a page never
# flashes the wrong scheme. Presentation only — nothing here changes what the
# surface *says*, there is no server state, and logging out keeps the look.
PREFS_COOKIE = "ls_prefs"
PREFS_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
THEMES = ("auto", "default", "vivid", "pastel", "dark", "cyberpunk")
LAYOUTS = ("rail", "topbar", "kiosk")
DEFAULT_THEME = "default"
DEFAULT_LAYOUT = "rail"
# Themes whose canvas is dark enough that Bootstrap's own chrome must follow
# (`data-bs-theme`). `auto` is deliberately absent: only the browser knows what
# the OS wants, so a small inline script resolves that one before first paint.
DARK_THEMES = ("dark", "cyberpunk")
# The wall-display layout: no bar, no rail, no filters, no user chrome — one slim
# line above the strip and the grid. Its exit writes the default layout back to
# the cookie, which is the whole of "leaving" a kiosk.
KIOSK_LAYOUT = "kiosk"


def _resolve_depth() -> int:
    """The render depth: an explicit ``?depth=`` wins, else the saved cookie,
    else :data:`MAX_DEPTH`. Clamped to ``0..MAX_DEPTH``."""
    raw = request.args.get("depth")
    if raw is None:
        raw = request.cookies.get("depth")
    try:
        depth = MAX_DEPTH if raw is None else int(raw)
    except ValueError:
        depth = MAX_DEPTH
    return max(0, min(depth, MAX_DEPTH))


def _resolve_flag(name: str, default: bool) -> bool:
    """A tri-source on/off view flag (like :func:`_resolve_depth`): an explicit form
    value wins (present ⇒ the switch was checked, or a manual ``?name=1``/``0``);
    else, on a form submission — marked by the hidden ``view`` field — an *absent*
    switch means off (an unchecked checkbox sends nothing); else the saved cookie;
    else ``default`` — so a default-on switch (leaf density) round-trips."""
    values = request.args.getlist(name)
    if values:
        return "1" in values
    if request.args.get("view"):
        return False
    cookie = request.cookies.get(name)
    if cookie is not None:
        return cookie == "1"
    return default


def _presentation() -> dict[str, str]:
    """This browser's theme and layout, read from the one presentation cookie
    (ADR-0029).

    Every failure mode lands on the defaults, independently per key: no cookie,
    an unparsable one, a key the roster no longer has, a value someone typed by
    hand. A preference is a *look*, so a bad one must never be able to break a
    page — the worst it can do is show the default.
    """
    values = parse_qs(request.cookies.get(PREFS_COOKIE, ""))
    theme = (values.get("theme") or [""])[0]
    layout = (values.get("layout") or [""])[0]
    return {
        "theme": theme if theme in THEMES else DEFAULT_THEME,
        "layout": layout if layout in LAYOUTS else DEFAULT_LAYOUT,
    }


@app.context_processor
def _inject_presentation() -> dict[str, object]:
    """Expose the presentation preferences to every template, so the shared
    header can render them onto `<body>` without per-route plumbing — the same
    trick :func:`_inject_engine_error` uses."""
    current = _presentation()
    return {
        "theme": current["theme"],
        "layout": current["layout"],
        "bs_theme": "dark" if current["theme"] in DARK_THEMES else "",
        "themes": THEMES,
        "layouts": LAYOUTS,
        # the kiosk's exit is a write of this value — the way out is simply
        # choosing the default layout again
        "default_layout": DEFAULT_LAYOUT,
    }


def _slot(name: str, /, **context: object) -> Markup:
    """The ``slot()`` template global (ADR-0034), with the one presentation rule
    the seam itself must not know about: **the kiosk renders no slot**.

    A wall display is read from across a room and has nobody at its keyboard — the
    same reason the pin control is hidden there. Deciding it here rather than in
    :mod:`little_sister.slots` keeps that module free of presentation, and keeps
    every filler from having to re-derive the layout to be a good citizen.
    """
    if has_request_context() and _presentation()["layout"] == KIOSK_LAYOUT:
        return Markup("")
    return slots.render(name, **context)


def _extension_assets() -> tuple[tuple[str, str], ...]:
    """``(kind, url)`` for every registered extension asset, in registration order
    — the ``extension_assets()`` template global (ADR-0037).

    The **library** emits the tags, so an extension never writes one into a page it
    does not own; the URL carries the asset's content hash, so a changed file is a
    changed URL. The kiosk gets none, for the same reason it renders no slot: a wall
    display has nobody at its keyboard, and code shipped to drive an interaction has
    nothing to drive there.
    """
    if has_request_context() and _presentation()["layout"] == KIOSK_LAYOUT:
        return ()
    return tuple(
        (asset.kind, url_for("extension_asset", package=asset.package,
                             member=asset.member, v=asset.digest))
        for asset in slots.assets())


app.jinja_env.globals["slot"] = _slot
app.jinja_env.globals["extension_assets"] = _extension_assets

# The declarative action list is a filler like any other (ADR-0038) — registered
# here rather than before the app import, because it is ours: a deployment's
# registrations have already landed by now, and both kinds share one rail.
register_builtin_fillers()


# Characters a browser does not read the way this code would. A backslash is
# normalized to `/`, and tab / CR / LF are stripped outright, before the URL is
# resolved — so `/\host` and `/<tab>/host` both *become* the scheme-relative
# `//host` that the check below is there to reject. Anything carrying one is
# refused rather than sanitized: a legitimate return path never contains them.
_NEXT_REJECTED = ("\\", "\t", "\n", "\r")


def _safe_next(raw: str | None) -> str:
    """A same-site path to return to after recording a preference.

    Only a plain path is ever accepted, so the form's hidden field cannot be
    turned into an open redirect: it must begin with a single `/`, and must not
    contain a character the browser would rewrite into a second one (see
    :data:`_NEXT_REJECTED`). Everything else falls back to the dashboard.
    """
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/status"
    if any(ch in raw for ch in _NEXT_REJECTED):
        return "/status"
    return raw


@app.route("/preferences", methods=["POST"])
def preferences() -> ResponseReturnValue:
    """Record this browser's presentation preferences (ADR-0029).

    The settings menu posts here and we send the viewer back where they were;
    the cookie is the whole store, so there is nothing to persist server-side
    and nothing to migrate. An unknown value is dropped in favor of what the
    browser already had, so a hand-edited form cannot write junk that every
    later page then has to defend against.
    """
    if "username" not in session:
        return redirect("/login")
    current = _presentation()
    theme = request.form.get("theme", "")
    layout = request.form.get("layout", "")
    chosen = {
        "theme": theme if theme in THEMES else current["theme"],
        "layout": layout if layout in LAYOUTS else current["layout"],
    }
    response = make_response(redirect(_safe_next(request.form.get("next"))))
    response.set_cookie(PREFS_COOKIE, urlencode(chosen),
                        max_age=PREFS_COOKIE_MAX_AGE, samesite="Lax")
    return response


@app.template_filter("status_slug")
def _status_slug(code: StatusCode) -> str:
    """Lower-case status name, used as a CSS class suffix (`s-ok`, `s-error`…)."""
    return code.name.lower()


@app.template_filter("url_branch")
def _url_branch(path: str) -> str:
    """A node's absolute path as a URL branch — without the leading `/`, so
    `url_for('status', branch=…)` builds `/status/system/alpha`, not `//…`
    (ADR-0016)."""
    return path.lstrip("/")


@app.template_filter("markdown")
def _markdown(text: object) -> Markup:
    """Render a Markdown block to safe HTML (ADR-0018)."""
    return render_markdown(str(text) if text else "")


@app.template_filter("markdown_inline")
def _markdown_inline(text: object) -> Markup:
    """Render Markdown inline (one line, no `<p>`) to safe HTML (ADR-0018)."""
    return render_markdown_inline(str(text) if text else "")


@app.template_filter("breadcrumbs")
def _breadcrumbs(branch: str) -> list[tuple[str, str]]:
    """Cumulative `(name, url-branch)` crumbs for a node's path, for the header
    trail — each ancestor links to its level, the last (current node) is rendered
    plain by the template. `system/alpha/disk` → `system`, `system/alpha`,
    `system/alpha/disk`."""
    crumbs: list[tuple[str, str]] = []
    accumulated = ""
    for segment in branch.split("/"):
        if not segment:
            continue
        accumulated = f"{accumulated}/{segment}" if accumulated else segment
        crumbs.append((segment, accumulated))
    return crumbs


#: A Markdown inline link, for the one thing :func:`_shorten` must not cut through.
_MARKDOWN_LINK = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")


@app.template_filter("shorten")
def _shorten(text: object, length: int = 200) -> str:
    """``text`` clamped to ``length`` characters, **never cutting inside a Markdown
    link**.

    The budget is a display one and the naive cut was fine until the result was
    rendered as Markdown. A reason line is often ``[#4821](https://forge…/4821)``,
    and a cut landing between the ``[`` and the ``)`` leaves the raw syntax and half
    a URL on the page — longer than the text it replaced and unreadable, which is the
    opposite of what a budget is for. So the cut backs up to the start of the link it
    would have split.

    Overshooting instead, when the link starts before anything else fits, is the
    right trade rather than a compromise: a link's *source* is long and what a reader
    sees is its label, so keeping it whole costs almost no rendered width and losing
    it costs the whole reason.

    Callers that never render Markdown are unaffected — text with no link reads
    exactly as before.
    """
    string = str(text)
    if len(string) <= length:
        return string
    cut = length - 1
    for link in _MARKDOWN_LINK.finditer(string):
        if link.start() >= cut:
            break
        if link.end() > cut:
            cut = link.start() or link.end()
            break
    return string[:cut].rstrip() + "…"


_STATUS_ALERT = {
    StatusCode.OK: "alert-success",
    StatusCode.WARN: "alert-warning",
    StatusCode.ERROR: "alert-danger",
    StatusCode.MAINTENANCE: "alert-primary",
    StatusCode.UNDEFINED: "alert-secondary",
}


@app.template_filter("status_alert")
def _status_alert(code: StatusCode) -> str:
    """Bootstrap alert class for a status code (the light info boxes)."""
    return _STATUS_ALERT.get(code, "alert-danger")


@app.template_filter("duration")
def _duration(seconds: int | None) -> str:
    """Humanise a number of seconds, e.g. 900 -> '15m'."""
    if not seconds:
        return "—"
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


@app.template_filter("elapsed")
def _elapsed(seconds: float | None) -> str:
    """Humanise a check runtime: milliseconds under a second (``412 ms``), one
    decimal under ten seconds (``3.1 s``), whole seconds beyond (``43 s``);
    ``—`` when no run has finished yet."""
    if seconds is None:
        return "—"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 10.0:
        return f"{seconds:.1f} s"
    return f"{seconds:.0f} s"


def _format_local(moment: datetime, fmt: str | None = None) -> str:
    """Format a datetime in the configured timezone and ``time_format``
    (config/settings.yaml); ``fmt`` overrides the format (never the timezone) for
    dense spots like the system table's time-of-day cells.

    The one place display timestamps are formatted, so the dashboard's poll
    stamp (served in the ``X-Rendered-At`` response header) matches every
    server-rendered time (ADR-0006) rather than the browser's locale.
    """
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment.astimezone(config.tzinfo).strftime(fmt or config.time_format)


@app.template_filter("localtime")
def _localtime(value: object, fmt: str | None = None) -> str:
    """Render an ISO-8601 timestamp in the configured timezone (config/settings.yaml),
    optionally with an explicit strftime ``fmt`` (the timezone always stays
    the configured one). A naive value is taken to be the server's local time.
    """
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return _format_local(moment, fmt)


def _filter_snapshot(node: StatusSnapshot,
                     hidden: set[StatusCode]) -> StatusSnapshot | None:
    """Drop nodes (and their subtrees) whose effective code is in `hidden`."""
    if node.code in hidden:
        return None
    kept = tuple(
        f for f in (_filter_snapshot(child, hidden) for child in node.children)
        if f is not None)
    return replace(node, children=kept)


def _node_meta_map(node: StatusSnapshot | None) -> dict[str, dict[str, str]]:
    """Path → rendered ``{title, about}`` HTML for the inspection popover
    (ADR-0019), for every node in ``node``'s subtree that has either. This static
    metadata is preloaded with the dashboard page; the hover card renders from it
    client-side, so it survives the polled grid swaps. (``description`` is not in
    the card — it stays on the leaf detail page.)"""
    out: dict[str, dict[str, str]] = {}
    if node is None:
        return out
    stack = [node]
    while stack:
        current = stack.pop()
        meta: dict[str, str] = {}
        if current.title:
            meta["title"] = str(render_markdown_inline(current.title))
        if current.about:
            meta["about"] = str(render_markdown(current.about))
        if meta:
            out[current.path] = meta
        stack.extend(current.children)
    return out


@dataclass(frozen=True)
class _MaintenancePin:
    """**One pin** — a node's, or one of its reasons' (ADR-0014, ADR-0036). The row
    type of the uncapped ``/maintenance`` table, which has room for a whole pin.

    **Two texts, and they must never share a column heading.** ``line`` is *what* is
    silenced — the reason line an entry pin covers, empty on a node pin, which covers
    the node whole — and ``note`` is *why*, the admin's justification. Both are
    called "reason" in the model (``ReasonLine.text`` and ``MaintenanceEntry.reason``)
    and they are not the same kind of thing at all; a table that shows one under the
    other's heading is the confusion this naming exists to prevent. The **slug never
    appears as text** — ADR-0036 makes it opaque — so it travels only as the deep
    link's ``?reason=`` value.

    ``order`` places a node's pins: its own first (``-1``), then its entries in the
    **check's** order, which is information (severity, API order) that sorting by an
    opaque slug would scramble. ``total`` is how many reasons the node had when this
    was read, carried so the popover can say *3 of 20* without a second walk, and
    ``expires_at`` so it can pick the soonest of several without re-parsing a
    humanized string.

    Both authorships travel (ADR-0014 amendment) because the two readings differ by
    surface: the popover has room for one name and takes ``set_by`` — the writer
    whose note it is showing — while the ``/maintenance`` table has room for the
    whole sentence, *pinned by Anna three days ago, last changed by Ben an hour ago*,
    and takes all four.
    """
    path: str
    title: str
    note: str
    remaining: str
    slug: str = ""
    line: str = ""
    order: int = -1
    total: int = 0
    expires_at: str = ""
    set_by: str = ""
    set_at: str = ""
    created_by: str = ""
    created_at: str = ""

    @property
    def edited(self) -> bool:
        """Whether this pin has been changed since it was made — the only case where
        naming both authorships says anything the creation line does not."""
        return bool(self.set_at) and self.set_at != self.created_at


@dataclass(frozen=True)
class _MaintenanceRow:
    """**One node** in the maintenance popover — never one per line.

    The popover is capped at ``maintenance_cap``, so a node with twenty pinned
    findings must not evict every other node from it: an entry-pinned node
    contributes exactly one row carrying a *count*, which is what its card already
    says in the grid (``StatusSnapshot.quiet_reasons``). One list, one type —
    ``quiet`` is zero on a plain node pin, and that is what tells the template which
    wording to use:

    * a node pin alone — the path, as before;
    * a node pin **and** entry pins — one row, the node pin leading (it already
      silences everything) with the count as a suffix, never two rows;
    * entries only, **all** of them — *all 20 reasons*, not *20 of 20*: this row is
      the only thing on the page that explains a card reading ``MAINTENANCE`` with
      no node pin on it;
    * entries only, some of them — *3 of 20 reasons*.

    ``remaining`` is the node pin's own time left where there is one, and otherwise
    the **soonest** of the entry pins — the next thing here to start alarming again.
    ``note`` / ``set_by`` are the node pin's, or a sole entry pin's; with several
    entry pins they are empty, because showing one of three justifications as if it
    were the row's is worse than showing none (``/maintenance`` carries them all).
    ``slug`` is likewise the sole entry pin's, for the deep link.
    """
    path: str
    title: str
    note: str
    remaining: str
    set_by: str = ""
    slug: str = ""
    pinned: bool = False
    quiet: int = 0
    total: int = 0


def _humanize_remaining(seconds: float) -> str:
    """A coarse 'time left' for the maintenance index — the largest one or two units
    (``2d 3h`` / ``5h`` / ``12m`` / ``< 1m``), or ``expired`` once past."""
    total = int(seconds)
    if total <= 0:
        return "expired"
    return _coarse_span(total)


#: The name, for the one filter that has to find it inside a sentence. The
#: template seam for a deployment's own name is `brand_name` (`_brand.html`); a
#: line that does not contain this simply passes through untouched.
BRAND_NAME = "little sister"


@app.template_filter("brand_accent")
def _brand_accent(text: object) -> Markup:
    """Set her name in the brand accent wherever it appears in a line.

    The /about stage's lines are prose with the name written into them, and the
    name wears `--ls-accent` everywhere else on the page — the wordmark, the
    story, the epigram — so it wears it here too rather than being the one place
    it goes unmarked. Everything around it is escaped, because these lines are
    text and only the wrapping is markup.
    """
    span = Markup('<span class="ls-accent">{}</span>').format(BRAND_NAME)
    return span.join(Markup.escape(part) for part in str(text).split(BRAND_NAME))


@app.template_filter("since")
def _since(value: datetime | None) -> str:
    """How long ago a moment was, phrased so a page left open cannot make it a lie.

    A server-rendered age is true only at the instant it is rendered, and the
    links page does not poll: a tab left open all afternoon would go on claiming
    *2m ago*. So the age is stated as a **floor** — ``> 2m ago``, ``> 3h ago``,
    ``> 2d 3h ago`` — which starts true and stays true however long the window
    sits there.

    Under a minute there is no floor worth stating (*less than a minute ago* is
    exactly the reading that rots), so the moment names itself: ``at 14:07``.
    That is also the common case right after a deliberate *check now*, where the
    clock time is the friendlier answer anyway.

    ``—`` when there is no moment, which on the links page means nothing has been
    asked yet rather than that the answer was fresh.
    """
    if value is None:
        return "—"
    elapsed = int((datetime.now() - value).total_seconds())
    if elapsed < 60:
        return f"at {_format_local(value, '%H:%M')}"
    return f"> {_coarse_span(elapsed)} ago"


def _coarse_span(total: int) -> str:
    """A span of seconds as its largest one or two units: ``2d 3h`` / ``5h`` /
    ``12m`` / ``< 1m``. Shared by the two readings of a span — how long is left,
    and how long ago it was — so they can never drift apart."""
    if total >= 86400:
        days, rest = divmod(total, 86400)
        hours = rest // 3600
        return f"{days}d {hours}h" if hours else f"{days}d"
    if total >= 3600:
        hours, rest = divmod(total, 3600)
        minutes = rest // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if total >= 60:
        return f"{total // 60}m"
    return "< 1m"


def _pin_view(node: StatusSnapshot, entry: MaintenanceEntry, now: datetime, *,
              slug: str = "", line: str = "", order: int = -1) -> _MaintenancePin:
    """One stored pin as an index row. ``slug`` / ``line`` / ``order`` are set for an
    **entry** pin and left at their defaults for a node's own."""
    try:
        remaining = (datetime.fromisoformat(entry.expires_at) - now).total_seconds()
    except ValueError:
        remaining = 0.0
    return _MaintenancePin(
        path=node.path, title=node.title, note=entry.reason,
        remaining=_humanize_remaining(remaining), slug=slug, line=line, order=order,
        total=len(node.reasons), expires_at=entry.expires_at,
        set_by=entry.set_by, set_at=entry.set_at,
        created_by=entry.created_by, created_at=entry.created_at)


def _maintenance_view(
    node: StatusSnapshot | None, now: datetime,
) -> tuple[list[_MaintenancePin], list[_MaintenancePin], set[str]]:
    """Surface the maintenance side-table (ADR-0014, ADR-0036) for the dashboard,
    read from the **unfiltered** snapshot so it survives hide-idle and any render
    depth: the **node** pins, the **entry** pins, and the set of every path that
    holds a pin somewhere below it (for the "contains maintenance" card pip).

    Three things rather than two because the two surfaces answer different questions
    and must not be given one shape: ``/maintenance`` lists every pin
    (:func:`_maintenance_pins`), the capped popover summarizes each node
    (:func:`_maintenance_rows`).

    **Only a node pin excludes a node from the ancestor set.** That exclusion exists
    for two reasons — the card shows its own pin, and a node pin cancels its whole
    subtree (ADR-0041), so a pip pointing below it would point at something
    already covered. An **entry** pin cancels nothing below it: it silences one of
    this node's own lines and leaves every child reporting exactly as before. So an
    entry-pinned container that also holds a pinned descendant gets the pip, and
    needs it; for its *own* entry pins it needs none, because its card already draws
    the quiet count. The pip earns its place here in **dense** mode: a node whose
    members are all pinned reads ``MAINTENANCE`` — neither warn nor error — so it
    collapses to a leaf chip, and a chip renders no reasons and no quiet count at
    all; the same disappearance happens under the depth ceiling and behind the branch
    cap's fold.

    Deliberately **not render-aware**: the set is computed from the snapshot, not
    from what the template ended up drawing, so the pip can be redundant beside a
    visible pinned box. That is already true of node pins today, and coupling the
    maintenance index to the layout would be the worse trade — please do not
    "improve" it.

    One consequence to know before reasoning about "ancestors": the set holds **every**
    ancestor of a pin, at every depth, but ``_status_grid.html`` only ever consumes it
    in a **card head** — never in ``render_nodes``. So a nested box's path can be in
    here and draw no pip; what the viewer gets is the pip on the card *containing* it,
    which is the intent. A statement about this set is not a statement about what is
    drawn.
    """
    node_pins: list[_MaintenancePin] = []
    entry_pins: list[_MaintenancePin] = []
    ancestors: set[str] = set()

    def walk(current: StatusSnapshot) -> bool:
        """Record ``current``'s pins; return whether it or its subtree holds one."""
        below = False
        for child in current.children:
            # Not `any(...)`: every child must be walked, and `any` short-circuits.
            if walk(child):
                below = True
        entry = current.maintenance_entry
        if entry is not None:
            node_pins.append(_pin_view(current, entry, now))
        here = False
        for order, reason_line in enumerate(current.reasons):
            if reason_line.maintenance is not None:
                here = True
                entry_pins.append(_pin_view(
                    current, reason_line.maintenance, now, slug=reason_line.slug,
                    line=reason_line.text, order=order))
        if below and entry is None:
            ancestors.add(current.path)
        return below or entry is not None or here

    if node is not None:
        walk(node)
    node_pins.sort(key=lambda pin: pin.path)
    entry_pins.sort(key=lambda pin: (pin.path, pin.order))
    return node_pins, entry_pins, ancestors


def _maintenance_pins(node_pins: list[_MaintenancePin],
                      entry_pins: list[_MaintenancePin]) -> list[_MaintenancePin]:
    """Every pin in one list for ``/maintenance``: by path, a node's own pin first,
    then its entries in the check's order."""
    return sorted(node_pins + entry_pins, key=lambda pin: (pin.path, pin.order))


def _maintenance_rows(node_pins: list[_MaintenancePin],
                      entry_pins: list[_MaintenancePin]) -> list[_MaintenanceRow]:
    """One row per **node** for the capped popover — see :class:`_MaintenanceRow`."""
    entries: dict[str, list[_MaintenancePin]] = {}
    for pin in entry_pins:
        entries.setdefault(pin.path, []).append(pin)
    rows = [
        _MaintenanceRow(
            path=pin.path, title=pin.title, note=pin.note,
            remaining=pin.remaining, set_by=pin.set_by, pinned=True,
            quiet=len(entries.get(pin.path, ())),
            total=pin.total)
        for pin in node_pins]
    pinned = {pin.path for pin in node_pins}
    for path, found in entries.items():
        if path in pinned:
            continue
        # The soonest to clear leads the row: `expires_at` is ISO-8601 from one
        # writer, so lexicographic order is chronological order.
        soonest = min(found, key=lambda pin: pin.expires_at)
        sole = found[0] if len(found) == 1 else None
        rows.append(_MaintenanceRow(
            path=path, title=found[0].title,
            note=sole.note if sole else "", remaining=soonest.remaining,
            set_by=sole.set_by if sole else "", slug=sole.slug if sole else "",
            quiet=len(found), total=found[0].total))
    rows.sort(key=lambda row: row.path)
    return rows


# Session signing key (ADR-0003): an explicit SECRET_KEY wins — its value may
# itself be a secret reference (`scheme://address`, ADR-0023 update note) —
# otherwise a random per-start key: secure by default, at the price of sessions
# resetting on restart (one worker, ADR-0001, so no cross-worker key skew). A
# malformed reference (unknown scheme) raises and fails startup loudly; an
# unresolvable one degrades to the random key with a warning — the dashboard
# must come up even while the secret store is down.
def _session_key() -> str:
    raw = os.environ.get("SECRET_KEY", "")
    try:
        key = resolve_setting(raw)
    except SecretError as error:
        logger.warning(
            "SECRET_KEY reference failed (%s); using a random per-start key — "
            "sessions reset on restart.", error)
        return token_hex(32)
    if key:
        return key
    logger.info("SECRET_KEY not set; using a random per-start key — "
                "sessions reset on restart.")
    return token_hex(32)


app.secret_key = _session_key()

USERS_ASPECT = "users"

# Load the allowed users from a deployment-controlled location (ADR-0020):
# LITTLE_SISTER_USERS names a single file and bypasses layering; otherwise the
# `users` aspect of the configuration directory (ADR-0031). Users are the one
# aspect that does **not** merge across roots — the first root declaring it wins
# whole, because merging identities across layers is a security question wearing a
# convenience costume.
_users_override = os.environ.get("LITTLE_SISTER_USERS", "")
_users_path: Path | None = (Path(_users_override) if _users_override
                            else sole_aspect_file(USERS_ASPECT))
if _users_path is None:
    raise FileNotFoundError(
        f"user list not found — no {USERS_ASPECT}.yaml in any configuration root "
        f"({', '.join(str(root.resolve()) for root in config_roots())}). Add "
        f"config/{USERS_ASPECT}.yaml (see users.example.yaml), or set "
        f"LITTLE_SISTER_USERS to a file elsewhere.")
try:
    with open(_users_path, encoding="utf-8") as users_file:
        users = yaml.safe_load(users_file)
except FileNotFoundError as exc:
    raise FileNotFoundError(
        f"user list not found at {str(_users_path)!r} — set LITTLE_SISTER_USERS "
        f"or place a {USERS_ASPECT}.yaml in a configuration root (see "
        f"users.example.yaml).") from exc

logger.info("little-sister started with %d configured user(s).", len(users or {}))

# API tokens for the JSON backend (ADR-0008): "name=token,name2=token2" — set
# directly, or as a value that is itself a secret reference (ADR-0023 update
# note). Unresolvable ⇒ no tokens (the API rejects all requests until restart)
# rather than a crash-loop; a malformed reference still fails startup loudly.
def _api_token_setting() -> str:
    try:
        return resolve_setting(os.environ.get("LITTLE_SISTER_API_TOKENS", ""))
    except SecretError as error:
        logger.warning(
            "LITTLE_SISTER_API_TOKENS reference failed (%s); the JSON API "
            "will reject all requests until restart.", error)
        return ""


api_tokens = parse_api_tokens(_api_token_setting())


# Start the monitoring engine once, in this (post-fork) process. Disable with
# LITTLE_SISTER_ENGINE=0. A bad check *config* is non-fatal — the web app still
# serves behind the banner below; an unusable configuration *tree* is not caught
# here at all and stops the process (ConfigError, ADR-0031).
engine: Engine | None = None
# Why the engine did not start: the ``CheckError`` reason when the checks config
# failed to load; ``None`` on success and on the deliberate
# ``LITTLE_SISTER_ENGINE=0`` disable. Feeds the header banner so a config typo
# doesn't take monitoring down with only a log line to show for it; persists
# until a restart with fixed config.
engine_error: str | None = None


def _start_engine_once() -> None:
    global engine, engine_error
    if engine is not None:
        return
    if os.environ.get("LITTLE_SISTER_ENGINE", "1").lower() in ("0", "false", "no"):
        logger.info("engine disabled via LITTLE_SISTER_ENGINE")
        return
    try:
        engine = create_engine()
    except CheckError as error:
        engine_error = str(error)
        logger.warning("engine not started: %s", error)
        return
    _restore_maintenance(engine)
    _seed_node_metadata(engine)
    engine.start()
    atexit.register(engine.stop)


@app.context_processor
def _inject_engine_error() -> dict[str, str | None]:
    """Expose :data:`engine_error` to every template, so the shared header
    partial can render its engine-not-started alert without per-route plumbing.
    (The login page does not include the header, so nothing leaks pre-login.)"""
    return {"engine_error": engine_error}


def _seed_node_metadata(engine: Engine) -> None:
    """Resolve `about` (nodes.yaml > inline check), seed it onto the tree, and run
    the startup consistency pass (ADR-0012). A bad `nodes.yaml` is logged, not
    fatal — node metadata must not stop monitoring."""
    try:
        metadata = resolve_metadata(engine.checks, load_nodes())
    except CheckError as error:
        logger.warning("node metadata not loaded: %s", error)
        return
    for path, meta in metadata.items():
        status_tree.set_about(path, meta.about)
        status_tree.set_title(path, meta.title)
    run_consistency_pass(engine.checks, metadata)


def _restore_maintenance(engine: Engine) -> None:
    """Attach the maintenance store, replay non-expired pins, and reap any whose
    path no configured check covers — once, post-fork before the engine runs
    (ADR-0014)."""
    store = MaintenanceStore()
    status_tree.use_maintenance_store(store)
    status_tree.restore_maintenance(store.load(), entry_pins=store.load_entries())
    reaped = status_tree.reap_uncovered(engine.check_roots())
    if reaped:
        logger.info("maintenance: reaped %d orphaned pin(s): %s",
                    len(reaped), ", ".join(sorted(reaped)))


_start_engine_once()


def _api_json(payload: dict[str, object], status_code: int = 200) -> Response:
    """A JSON API response; echoes an inbound X-Flow-Id if present (ADR-0008)."""
    resp = make_response(jsonify(payload), status_code)
    flow = request.headers.get("X-Flow-Id")
    if flow:
        resp.headers["X-Flow-Id"] = flow
    return resp


def _api_problem(status_code: int, title: str,
                 detail: str | None = None) -> Response:
    """An application/problem+json error response (RFC 9457)."""
    resp = _api_json(problem(status_code, title, detail), status_code)
    resp.mimetype = "application/problem+json"
    return resp


@app.route('/')
def index() -> ResponseReturnValue:
    return redirect("/status")


@app.route('/login', methods=['GET', 'POST'])
def login() -> ResponseReturnValue:
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]["password"] == password:
            session['username'] = username
            session["firstname"] = users[username]["firstname"]
            session["lastname"] = users[username]["lastname"]
            session["admin"] = bool(users[username].get("admin", False))
            return redirect('/status')
        logger.warning("Failed login attempt for username %r.", username)
        return render_template('login.html', error='Invalid username or password')
    return render_template('login.html', error=None)


@app.route('/logout')
def logout() -> ResponseReturnValue:
    session.clear()
    return redirect('/login')


def _split_heartbeat(
    node: StatusSnapshot | None,
) -> tuple[StatusSnapshot | None, StatusSnapshot | None]:
    """Lift the engine's self-heartbeat (ADR-0005) out of a root snapshot's
    children so the dashboard can render it as the status strip (ADR-0024) rather than
    a near-empty grid card. Returns ``(node_without_heartbeat, heartbeat)``.

    The heartbeat is only ever a child of the root overview, so on a branch page
    (or when the engine is disabled) this returns ``node`` unchanged with
    ``None``. A heartbeat that grew children is not lifted either: the strip is
    a one-line bar and must never hide a subtree, so such a node stays a grid
    card. (The loader keeps custom checks off the reserved line — this guard is
    belt and braces, and the fallback for future engine-owned children.)
    Splitting happens before the hide-ok/hide-idle filter, so the strip stays
    visible regardless of the filters. The JSON API is untouched: it serialises
    the whole snapshot upstream of this call.
    """
    if node is None:
        return None, None
    heartbeat: StatusSnapshot | None = None
    kept: list[StatusSnapshot] = []
    for child in node.children:
        if child.path == HEARTBEAT_PATH and not child.children:
            heartbeat = child
        else:
            kept.append(child)
    if heartbeat is None:
        return node, None
    return replace(node, children=tuple(kept)), heartbeat


@app.route('/status')
@app.route('/status/<path:branch>')
def status(branch: str = "") -> ResponseReturnValue:
    # JSON backend mode (ADR-0008): content-negotiated, token-gated, read-only.
    if request.accept_mimetypes.best_match(
            ("text/html", "application/json")) == "application/json":
        if authenticate(request.headers.get("Authorization"), api_tokens) is None:
            return _api_problem(401, "Unauthorized",
                                "A valid bearer token is required.")
        node = status_tree.snapshot(branch)
        if node is None:
            return _api_problem(404, "Not Found",
                                f"No status node at path {branch!r}.")
        return _api_json(status_envelope(node))
    if 'username' not in session:
        return redirect('/login')
    node = status_tree.snapshot(branch)
    # A leaf node (a check) gets its own detail page.
    if branch and node is not None and not node.children:
        periods = status_tree.history(branch)
        # The current period's start — or None when this node has no transition of its
        # own to bound one, in which case the page reports the single observation
        # instead of a from/until of one instant (ADR-0027).
        since = periods[-1].since if periods else None
        # `?reason=<slug>` names one line of this node — the addressing shape
        # ADR-0036 decision 12 settled on, never a path segment. The maintenance
        # index links here with it, because on a node with 150 findings "the right
        # page" is not the same as "the line", and the page marks the one it names.
        focus = request.args.get('reason', '')
        # A pin whose slug the current run does not report is **suspended, not
        # deleted** (ADR-0036 decision 6): the pin is real and the line is absent.
        # This is the only surface that can say so — a fragment could only have
        # failed to scroll — and it is the moment an operator most needs it said.
        focus_orphan = (
            status_tree.entry_maintenance(branch, focus)
            if focus and all(line.slug != focus for line in node.reasons)
            else None)
        return render_template('check.html', username=session['username'],
                               firstname=session['firstname'], node=node,
                               branch=branch, since=since, focus=focus,
                               focus_orphan=focus_orphan,
                               is_admin=session.get('admin', False),
                               maintenance_default=config.maintenance_default_expiry)
    # Lift the engine self-heartbeat into the status strip (ADR-0024) before filtering,
    # so it shows there always — never as a card, never hidden by hide-ok.
    node, heartbeat = _split_heartbeat(node)
    hide_ok = _resolve_flag('hide_ok', False)
    hide_idle = _resolve_flag('hide_idle', False)
    dense = _resolve_flag('dense', True)
    # Surface the maintenance set (ADR-0014) from the *unfiltered* snapshot, so the
    # index and the "contains maintenance" pips survive hide-idle and any depth.
    now = datetime.now()
    node_pins, entry_pins, maintenance_ancestors = _maintenance_view(node, now)
    maintenance_rows = _maintenance_rows(node_pins, entry_pins)
    if node is not None and (hide_ok or hide_idle):
        hidden: set[StatusCode] = set()
        if hide_ok:
            hidden.add(StatusCode.OK)
        # hide-idle hides only never-reported (UNDEFINED) nodes; maintenance is an
        # intentional admin state, not idle, and stays visible (the index/pip surface
        # it, so bundling it with idle only made it harder to find).
        if hide_idle:
            hidden.add(StatusCode.UNDEFINED)
        node = replace(node, children=tuple(
            f for f in (_filter_snapshot(c, hidden) for c in node.children)
            if f is not None))
    depth = _resolve_depth()
    # One server-formatted stamp per response (ADR-0006): rendered into the page
    # so it dates its data from the first paint (page JavaScript cannot read
    # navigation-response headers), and sent as X-Rendered-At so the poll loop
    # reads the same clock — "updated …" / "could not refresh — last ok …" honour
    # settings.yaml's time_format and timezone, not the browser's locale.
    rendered_at = _format_local(now)
    if request.args.get('fragment'):
        body = render_template('_status_grid.html', node=node, branch=branch,
                               max_depth=depth, hide_ok=hide_ok,
                               hide_idle=hide_idle, dense=dense,
                               is_admin=session.get('admin', False),
                               heartbeat=heartbeat, reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_rows=maintenance_rows,
                               maintenance_ancestors=maintenance_ancestors)
    else:
        # The hover card (ADR-0019) must know the strip too: the lifted
        # heartbeat's nodes.yaml title/about join the map like any node's.
        node_meta = _node_meta_map(node) | _node_meta_map(heartbeat)
        body = render_template('status.html', username=session['username'],
                               firstname=session['firstname'], node=node,
                               branch=branch, max_depth=depth,
                               depth_limit=MAX_DEPTH, hide_ok=hide_ok,
                               hide_idle=hide_idle, dense=dense,
                               is_admin=session.get('admin', False),
                               maintenance_default=config.maintenance_default_expiry,
                               heartbeat=heartbeat, node_meta=node_meta,
                               rendered_at=rendered_at,
                               reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_rows=maintenance_rows,
                               maintenance_ancestors=maintenance_ancestors)
    response = make_response(body)
    response.headers['X-Rendered-At'] = rendered_at
    # Persist a view choice only when the viewer set it explicitly (never on the
    # ~10s poll fragment), so the chosen shape sticks across visits.
    if not request.args.get('fragment'):
        if 'depth' in request.args:
            response.set_cookie('depth', str(depth),
                                max_age=VIEW_COOKIE_MAX_AGE, samesite='Lax')
        for name, value in (('hide_ok', hide_ok), ('hide_idle', hide_idle),
                            ('dense', dense)):
            if request.args.getlist(name) or request.args.get('view'):
                response.set_cookie(name, '1' if value else '0',
                                    max_age=VIEW_COOKIE_MAX_AGE, samesite='Lax')
    return response


@app.route('/history/<path:path>')
def history(path: str) -> ResponseReturnValue:
    if 'username' not in session:
        return redirect('/login')
    node = status_tree.snapshot(path)
    periods = list(reversed(status_tree.history(path)))
    return render_template('history.html', username=session['username'],
                           firstname=session['firstname'], node=node,
                           branch=path, periods=periods)


_DEFAULT_MAINTENANCE_SECONDS = 7 * 24 * 3600   # hard fallback if config is unusable

# A maintenance window has to be a **positive** number of seconds, and a bounded one
# (ADR-0014 amendment). ADR-0014 promised a *finite* expiry; finite was never enough:
#
# * a zero or negative duration parses cleanly (`parse_duration("-1d")` is -86400),
#   lands `expires_at` in the past, and the next scheduler sweep drops the entry — so
#   the reason text and both authorships are gone within a tick, behind a redirect
#   that looked like a success. That is the lost-explanation failure the
#   compare-and-set guard exists to prevent, arriving through the other door;
# * an enormous one overflows. `99999999d` parses and then raises `OverflowError`
#   from `datetime.now() + timedelta(...)`, and `inf` raises it inside
#   `parse_duration` itself — which is not a `CheckError`, so catching that alone
#   turned a typo into a 500.
#
# A year is far past any real window and keeps the arithmetic nowhere near the
# overflow, so it is the ceiling. Out of range is **refused**, not clamped: an admin
# who typed `-1d` and silently got a week has learned nothing.
MIN_MAINTENANCE_SECONDS = 1
MAX_MAINTENANCE_SECONDS = 365 * 24 * 3600


class _BadDuration(Exception):
    """A duration this cannot turn into a positive, bounded window. Carries the
    sentence the form shows."""


def _maintenance_seconds(raw: str) -> int:
    """Seconds for a maintenance window: an explicit duration (``2h`` / ``3d``) when
    given, else the configured default (ADR-0014).

    Raises :class:`_BadDuration` for anything that is not a positive, bounded number
    of seconds. The **configured default** is the one value that still falls back
    rather than refusing — a deployment's own `settings.yaml` typo must not make the
    form unusable, and the hard fallback is a week.
    """
    text = raw.strip()
    if not text:
        try:
            fallback = parse_duration(config.maintenance_default_expiry,
                                      _DEFAULT_MAINTENANCE_SECONDS)
        except (CheckError, OverflowError, ValueError):
            fallback = _DEFAULT_MAINTENANCE_SECONDS
        if not MIN_MAINTENANCE_SECONDS <= fallback <= MAX_MAINTENANCE_SECONDS:
            fallback = _DEFAULT_MAINTENANCE_SECONDS
        return fallback
    try:
        seconds = parse_duration(text, _DEFAULT_MAINTENANCE_SECONDS)
    except (CheckError, OverflowError, ValueError) as error:
        raise _BadDuration(
            f"{text!r} is not a duration — write it as 2h, 3d, 90m or a number "
            f"of seconds.") from error
    if seconds < MIN_MAINTENANCE_SECONDS:
        raise _BadDuration(
            f"A maintenance window has to be in the future — {text!r} is not. "
            f"Write it as 2h, 3d, 90m or a number of seconds.")
    if seconds > MAX_MAINTENANCE_SECONDS:
        raise _BadDuration(
            f"{text!r} is longer than a year, which is longer than a maintenance "
            f"window is ever meant to be. Pick something shorter.")
    return seconds


@app.route('/maintenance', methods=['POST'])
def maintenance() -> ResponseReturnValue:
    """Set, edit or clear a pin — a **compare-and-set** write (ADR-0014 amendment).

    Every form here carries the entry's ``set_at`` as a hidden token: the write
    names the pin it believes it is replacing, and an empty token says *"I believe
    nothing is pinned"*. When the table says otherwise the write is refused whole —
    nothing is written — and the admin gets the conflict page with both texts and
    their own words intact. A post with **no** ``set_at`` field at all (a hand-rolled
    client, never one of our forms) writes unguarded, exactly as before.
    """
    if 'username' not in session:
        return redirect('/login')
    if not session.get('admin'):
        abort(403)
    path = request.form['path']
    token = request.form.get('set_at')
    clearing = request.form.get('action') == 'clear'
    typed = request.form.get('reason', '').strip()
    duration = request.form.get('duration', '')
    # A `slug` names **one reason** of the node instead of the node itself
    # (ADR-0036): same form, same token, same expiry — one key deeper. The field is
    # `slug` rather than `reason` because `reason` is already this form's
    # explanation text; the *addressing* shape the ADR fixes is the query parameter
    # (`?reason=<slug>`), which is a different namespace.
    slug = request.form.get('slug', '')
    # The card dialog says where it was opened (`next`), so pinning from the
    # wall returns to the wall; validated like the preferences form's field.
    # Without it — the leaf and branch page forms — the node's page stays the
    # destination, which for those pages is the page itself.
    next_raw = request.form.get('next', '')
    where = _safe_next(next_raw) if next_raw else url_for(
        'status', branch=path.lstrip('/'))
    refused = partial(_maintenance_refused, path=path, slug=slug, back=where,
                      clearing=clearing, mine=typed, duration=duration,
                      token=token or '')
    if clearing and slug:
        write = status_tree.clear_entry_maintenance(path, slug,
                                                    expected_set_at=token)
    elif clearing:
        write = status_tree.clear_maintenance(path, expected_set_at=token)
    else:
        try:
            seconds = _maintenance_seconds(duration)
        except _BadDuration as bad:
            # Nothing is written and the admin's words come back — the same
            # posture as a refused compare-and-set, for the same reason: a write
            # that silently did something other than what was asked is the thing
            # this route is not allowed to do (ADR-0014 amendment).
            return refused(problem=str(bad), stored=None)
        expires_at = datetime.now() + timedelta(seconds=seconds)
        # A blank reason on an **edit** means "I did not touch this field", so the
        # stored text stays; on a new pin there is nothing to keep and the literal
        # `maintenance` is the honest placeholder.
        held = _held_reason(path, slug, token)
        reason = typed or held or 'maintenance'
        setter = (partial(status_tree.set_entry_maintenance, path, slug) if slug
                  else partial(status_tree.set_maintenance, path))
        write = setter(reason, expires_at=expires_at,
                       set_by=session.get('username', ''),
                       expected_set_at=token)
    if write.refused:
        return refused(problem=None, stored=write.current)
    return redirect(where)


def _held_reason(path: str, slug: str, token: str | None) -> str:
    """The reason text already stored for this pin, for an edit that left the field
    blank. Empty when there is nothing pinned — or when the caller believes there is
    not (an empty token), in which case keeping someone else's words would be
    stranger than the placeholder."""
    if not token:
        return ""
    entry = (status_tree.entry_maintenance(path, slug) if slug
             else status_tree.maintenance_entry(path))
    return entry.reason if entry is not None else ""


def _maintenance_refused(*, path: str, slug: str, back: str, clearing: bool,
                         mine: str, duration: str, token: str,
                         problem: str | None,
                         stored: MaintenanceEntry | None) -> ResponseReturnValue:
    """The page a refused write lands on: nothing was saved, here is why, and here
    are your own words back. One page for both refusals — a stale token and a
    duration we will not accept — because the admin's situation is the same.

    On a bad duration the form carries the **original** token, because nothing about
    the stored pin moved; a refused compare-and-set is the case that needs a
    refreshed one, and that branch reads it off the entry it is showing.
    """
    return render_template(
        'maintenance_conflict.html', username=session['username'],
        firstname=session['firstname'], path=path, back=back,
        clearing=clearing, stored=stored, slug=slug, problem=problem,
        mine=mine, duration=duration, token=token,
        maintenance_default=config.maintenance_default_expiry)


@app.route('/maintenance', methods=['GET'])
def maintenance_overview() -> ResponseReturnValue:
    """The full, uncapped maintenance overview as its own page — every pin, node and
    entry alike (ADR-0014, ADR-0036), with what it silences, how long is left, why,
    and who is behind it. Read from the whole snapshot, so it is depth- and
    filter-independent. Viewer-visible and bookmarkable; the strip pill's popover
    "+N more" links here.

    This is the page that has room for **one row per pin**, which is what makes the
    popover's one-row-per-node summary safe: an admin asking *what is silenced right
    now?* gets a complete answer somewhere."""
    if 'username' not in session:
        return redirect('/login')
    node_pins, entry_pins, _ = _maintenance_view(
        status_tree.snapshot(""), datetime.now())
    return render_template('maintenance.html', username=session['username'],
                           firstname=session['firstname'],
                           pins=_maintenance_pins(node_pins, entry_pins))


@app.route('/events')
def events() -> ResponseReturnValue:
    if 'username' not in session:
        return redirect('/login')
    recent = list(reversed(status_tree.recent_events()))
    return render_template('events.html', username=session['username'],
                           firstname=session['firstname'], events=recent)


@app.route('/system')
def system() -> ResponseReturnValue:
    if 'username' not in session:
        return redirect('/login')
    if not session.get('admin'):
        abort(403)
    # Same freshness contract as the dashboard (ADR-0005): one server-formatted
    # stamp per response, seeded into the page and sent as X-Rendered-At for
    # the ~10s fragment poll (`fragment=1` returns just the info block).
    rendered_at = _format_local(datetime.now())
    info = engine.info() if engine is not None else None
    if request.args.get('fragment'):
        body = render_template('_system_info.html', info=info)
    else:
        # The extension seams, outside the polled fragment because they are
        # settled at startup and never change while the process runs: which
        # package fills which template slot (ADR-0034) and which configuration
        # aspects a dependent package added (ADR-0035). A seam nobody can see
        # from the running instance is indistinguishable from one that silently
        # did not take.
        body = render_template('system.html', username=session['username'],
                               firstname=session['firstname'],
                               version=__version__, info=info,
                               rendered_at=rendered_at,
                               slot_fillers=slots.all_fillers(),
                               extra_aspects=registered_aspects())
    response = make_response(body)
    response.headers['X-Rendered-At'] = rendered_at
    return response


@app.route('/copy')
def copy() -> ResponseReturnValue:
    if 'username' in session:
        return render_template('text.html', username=session['username'],
                               firstname=session['firstname'])
    return redirect('/login')


@app.route('/links')
def links() -> ResponseReturnValue:
    """The shared toolbox: the deployment's curated links (ADR-0030).

    The configuration is re-read only when the file actually changed, so an
    operator fixing a URL sees it on the next reload and the process keeps the
    history it has in memory.

    Opening the page is also what **triggers** a reachability pass, and only
    when the newest answer is older than the configured interval (ADR-0030 §9,
    amended). The call starts a daemon thread and returns, so the render never
    waits on the network: the page shows what is already in memory, each verdict
    with its own age, and the answers this open triggers land on the next.

    ``icon_names`` is the roster the empty state shows: every name a registered
    pack defines, so somebody who has not written the file yet can read the
    marks off the page instead of out of the log. It is the **registry**, not
    :attr:`LinksConfig.icons` — the deployment's own map may name a remote URL or
    suppress a name, and neither has bytes at ``/links/icon``.
    """
    if 'username' not in session:
        return redirect('/login')
    links_config = current_links()
    link_probe.refresh_if_due(links_config)
    return render_template('links.html', username=session['username'],
                           firstname=session['firstname'],
                           links_config=links_config,
                           links_file=_links_file_hint(),
                           probe=link_probe.page_view(links_config),
                           icon_names=known_names())


@app.route('/links/check', methods=['POST'])
def links_check() -> ResponseReturnValue:
    """Probe the links page's targets **now**, then redirect back to it.

    The shape `/preferences` and `/maintenance` already use, and for the same
    reasons: a `GET` would let a reload, a prefetch or a crawler spend outbound
    requests, and the redirect is what stops a refresh from firing a second pass.
    It is a button in a form, so it needs no JavaScript.

    Unlike an open, this **waits** — under a deadline, joining the pass already
    running if there is one (ADR-0030, amended). Whatever has not answered by
    then keeps its previous verdict and age while the pass finishes behind the
    response.

    Open to **every logged-in viewer**, not only an admin: whoever maintains
    `links.yaml` is not necessarily one, and this is the control that person
    needs most. It is the same call the problems block above it already makes.
    """
    if 'username' not in session:
        return redirect('/login')
    link_probe.refresh_now(current_links())
    return redirect(_safe_next(request.form.get('next')))


def _links_file_hint() -> str:
    """Where a deployment's first `links.yaml` would go — for the empty state.

    Names the **first** configuration root, since that is where somebody who has
    not written the file yet should put it. Falls back to the relative default if
    the tree cannot be resolved, which is a case the startup contract has already
    refused, so this is belt rather than braces.
    """
    try:
        return str(config_roots()[0] / f"{LINKS_ASPECT}/{LINKS_ASPECT}.yaml")
    except ConfigError:
        return f"config/{LINKS_ASPECT}/{LINKS_ASPECT}.yaml"


@app.template_filter('site_origin')
def _site_origin(url: str) -> str:
    """A URL's `scheme://host` — the origin its favicon would be served from.

    The step of the icon search path before the neutral glyph (ADR-0030 §3), and
    the reason it is a filter: only the template knows which entry it is drawing.
    Empty when there is no host to ask, which the loader's scheme check already
    makes unreachable for a link that survived loading.
    """
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""


@app.route('/ext/<package>/<member>')
def extension_asset(package: str, member: str) -> ResponseReturnValue:
    """Serve one registered extension asset (ADR-0037).

    Neither argument is ever used to build a path: the pair is looked up in the
    registry and the answer carries what to read, so a member that walks out of the
    package does not exist to begin with — the same posture as the icon route.

    Served from **our** origin rather than left to a third-party URL, which is what
    keeps a future ``script-src 'self'`` able to cover code the library never saw.
    Login-gated like every other surface: an extension's script is written for the
    deployment's own operators, and its source can name their internals.
    """
    if 'username' not in session:
        return redirect('/login')
    asset = slots.asset_for(package, member)
    if asset is None:
        abort(404)
    try:
        payload = slots.read_asset(asset)
    except OSError:
        # The package was replaced under a running process; a 404 is honest.
        abort(404)
    response = make_response(payload)
    response.mimetype = asset.content_type
    # The URL carries the asset's own content hash, so a changed file is a changed
    # URL and this answer can be cached hard. Private: the surface is login-gated.
    response.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
    response.add_etag()
    return response.make_conditional(request)


@app.route('/links/icon/<variant>/<name>')
def link_icon(variant: str, name: str) -> ResponseReturnValue:
    """Serve one resolved icon, for the background named by ``variant``.

    Every rung of the search path that holds *bytes* is served from here — the
    deployment's own file, a registered pack's package data, the built-in pack — so
    the page has one URL shape for all of them and the icons ship from our own origin
    (ADR-0030 §3). A **remote** icon is the exception and is 404 here: it is emitted
    as its own URL, never proxied, because proxying it would quietly make this
    instance fetch whatever a config file names.

    ``name`` is never used to build a path. It is looked up in the resolved
    registry and the answer carries the file, so a name that walks out of the
    configuration tree does not exist to begin with.

    Login-gated like every other surface — a deployment's toolbox names its internal
    hosts, and so do the icons beside them.
    """
    if 'username' not in session:
        return redirect('/login')
    if variant not in ('on-light', 'on-dark'):
        abort(404)
    icon = current_links().icon_for(name)
    if icon is None or icon.suppressed:
        abort(404)
    source = icon.file_for(variant)
    if source is None or source.url:
        abort(404)
    try:
        payload, content_type = read_icon(source)
    except (OSError, ValueError):
        # The file went away under a running process, or something bypassed the
        # loaders' type allowlist. Either way the page's own fallback is the answer.
        abort(404)
    response = make_response(payload)
    response.mimetype = content_type
    # Private: the surface is login-gated. Short, because an operator who swaps an
    # icon file is watching this page while they do it — the ETag makes the repeat
    # request cheap without making the swap invisible.
    response.headers['Cache-Control'] = 'private, max-age=300'
    response.add_etag()
    return response.make_conditional(request)


@app.route('/about')
def about() -> ResponseReturnValue:
    """The identity page: who this is and why it is called that.

    Login-required like every other surface — it is not a public shopfront, and
    it names the version of the instance you are actually looking at, which is
    not something to hand to anyone who asks.

    The hero's terms and lines are **drawn per render** from the pools in
    :mod:`little_sister.watch_lines`, so a second visit reads differently:
    there is far more text there than one visit shows. The inner ring and the
    nine-line ending are the fixed parts — one answers to the paragraph below
    it, the other is the promise the page exists to make.
    """
    if 'username' not in session:
        return redirect('/login')
    return render_template('about.html', username=session['username'],
                           firstname=session['firstname'],
                           version=__version__,
                           rings=watch_lines.rings(),
                           says=watch_lines.says())


@app.route('/favicon.ico')
def favicon() -> ResponseReturnValue:
    return redirect('/static/favicon.ico')


if __name__ == '__main__':
    # use_reloader=False so the engine isn't started twice in dev.
    app.run(debug=True, use_reloader=False)
