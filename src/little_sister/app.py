import atexit
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from secrets import token_hex
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    has_request_context,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.sessions import SecureCookieSessionInterface
from flask.typing import ResponseReturnValue
from jinja2 import ChoiceLoader, StrictUndefined
from markupsafe import Markup

from little_sister import (
    __version__,
    csp,
    identity,
    link_probe,
    local_login,
    readiness,
    self_report,
    slots,
    system_admin,
    watch_lines,
)
from little_sister.actions import register_builtin_fillers
from little_sister.api import authenticate, parse_api_tokens, problem, status_envelope
from little_sister.checks import CheckError, parse_duration, plain
from little_sister.checks.base import DURATION_UNITS, TypeOrigin, registered_types
from little_sister.config import config
from little_sister.config_dir import (
    CONFIG_DIR_ENV,
    announce_aspects,
    aspect_owner,
    config_roots,
    fatal,
    registered_aspects,
)
from little_sister.copy_action import register_copy_filler
from little_sister.copy_status import (
    TimeStyle,
    format_copy_markdown,
    format_node_markdown,
    format_reason_markdown,
)
from little_sister.dashboard_layout import dashboard_layout
from little_sister.engine import Engine, EngineInfo, create_engine
from little_sister.errors import ConfigError
from little_sister.icons import known_names, read_icon
from little_sister.instance import this_instance
from little_sister.keeper import registered_keeper
from little_sister.links import LINKS_ASPECT, current_links
from little_sister.logger import logger
from little_sister.maintenance import MaintenanceEntry, MaintenanceStore
from little_sister.nodes import load_nodes, resolve_metadata, run_consistency_pass
from little_sister.origins import PackageOrigin, package_origin
from little_sister.paths import shown_path
from little_sister.render import render_markdown, render_markdown_inline
from little_sister.secrets import SecretError, registered_resolvers, resolve_setting
from little_sister.spans import coarse_span, format_duration, format_span, local_time
from little_sister.state import EVENTS_FILE, StateLayer
from little_sister.status import HEARTBEAT_PATH, StatusCode, on_same_line
from little_sister.titles import Labeled, label_parts, shown_title
from little_sister.tree import StatusSnapshot, events_from_payload, status_tree
from little_sister.users import read_avatar

app = Flask(import_name=__name__)
app.jinja_env.undefined = StrictUndefined
# The template supplies the current filtered snapshot and render depth; this
# helper turns only that stable topology into the card weights and span plans.
app.jinja_env.globals["dashboard_layout"] = dashboard_layout
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


def _connection_is_secure() -> bool:
    """Whether the request being served arrived over TLS (ADR-0065).

    **The transport answers this** — not a configuration value, not the host name, not
    a forwarded header we chose to believe. gunicorn sets ``wsgi.url_scheme`` from the
    socket it is holding, so this is true exactly when *this process* terminated a TLS
    connection: locally the browser's, and behind a load balancer the second one the
    balancer opens to the instance. Both are the same fact arrived at the same way,
    which is what lets one rule cover a laptop and a cloud account.

    Outside a request there is no connection to ask about, so nothing is marked.
    """
    return has_request_context() and request.is_secure


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
        # Deployment-wide card head style (settings.yaml `card_status_line`):
        # `below` gives every card a standing status line under its title row;
        # the compact default keeps the cluster beside it. Rendered as a body
        # attribute the stylesheet branches on; a per-viewer override is a
        # later step (backlog).
        "card_status_line": config.card_status_line,
        # Deployment-wide column mode (settings.yaml `dashboard_columns`,
        # ADR-0056): `flow` lets the status grid publish its width-priced span
        # plan; `plain` withholds it, leaving the plain auto-fill grid — the
        # exact page a browser without JavaScript shows. A per-viewer value
        # and a possible `packed` mode are later steps of this same enum.
        "dashboard_columns": config.dashboard_columns,
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
register_copy_filler()


# The one inline script the documents carry: the theme bootstrap, which resolves
# `auto` before first paint and therefore cannot be a file (the partial says why).
# One partial, so one hash — that is what folding the login page's copy away bought.
_THEME_BOOTSTRAP = "_theme_bootstrap.html"

# The text between a bare <script> and its close. Only our own partial is read with
# this, and it holds exactly one such element with no attributes.
_INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.DOTALL)

# The header the first policy ships under (ADR-0048 §6): it reports, it blocks
# nothing. Enforcement — and which directives graduate first — is a later decision.
CSP_HEADER = "Content-Security-Policy-Report-Only"

# A violation report is small; anything larger is not one, and this endpoint takes no
# authentication (a violation on the login page has no session), so it is bounded
# before it is parsed rather than after.
CSP_REPORT_LIMIT = 64 * 1024

# Every control character in a reported field becomes a space before it is logged: a
# report is attacker-influenced text, and a newline in it would forge a second log
# line. `\x85` and `\u2028`/`\u2029` are in here because some log readers break lines
# on them too.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")

# How much of one reported field reaches the log. A report is attacker-influenced
# text — a blocked URI is whatever the page tried to load — and one line per
# violation is the whole point of logging them.
CSP_FIELD_LIMIT = 200


def _inline_scripts() -> tuple[str, ...]:
    """The exact text of every inline script our pages carry, for :func:`csp.assemble`.

    Read from the rendered partial rather than written out again here: a browser
    hashes the element's text content byte for byte, so a second copy of it in Python
    would be a copy that can drift — which is the failure this returns nothing for
    instead. Rendered through the app's own environment, so it is the same bytes the
    include emits.
    """
    try:
        rendered = app.jinja_env.get_template(_THEME_BOOTSTRAP).render()
    except Exception as error:
        logger.exception("csp: %s could not be rendered", _THEME_BOOTSTRAP)
        self_report.startup.note(
            "csp.theme-hash",
            plain(f"{_THEME_BOOTSTRAP} could not be rendered ({error!r}), so its "
                  f"hash is not in the policy — the theme bootstrap is reported on "
                  f"every page (ADR-0048)"))
        return ()
    # An HTML parser normalizes CRLF to LF in an element's text before the hash is
    # taken, so a CRLF checkout would otherwise hash bytes no browser ever sees.
    found = tuple(match.group(1).replace("\r\n", "\n")
                  for match in _INLINE_SCRIPT.finditer(rendered))
    if not found:
        self_report.startup.note(
            "csp.theme-hash",
            plain(f"no inline <script> found in {_THEME_BOOTSTRAP}, so its hash is "
                  f"not in the policy (ADR-0048)"))
    return found


# The Content-Security-Policy, assembled **here** — at application creation, after
# every registration has run and the configuration is loaded, and never at module
# import, because import is when a dependent package's contributions are still
# arriving (ADR-0048 §1). There is deliberately no policy constant to find.
csp_policy = csp.assemble(inline_scripts=_inline_scripts())
logger.info("csp: %s: %s", CSP_HEADER, csp_policy.header())


@app.after_request
def _content_security_policy(response: Response) -> Response:
    """Attach the assembled policy to every document (ADR-0048).

    The application's first ``after_request`` hook. HTML only: the policy governs how
    a *document* may be built, so putting it on the JSON API's responses or on a
    static file would be noise a browser ignores anyway. The ~10s poll fragments are
    HTML and do carry it, which costs a header and is honest — they are page content.
    """
    if response.mimetype == "text/html":
        response.headers[CSP_HEADER] = csp_policy.header()
    return response


@app.route(csp.REPORT_PATH, methods=["POST"])
def csp_report() -> ResponseReturnValue:
    """Log one violation report at ``WARNING`` (ADR-0048 §6).

    **No login gate, deliberately:** a violation on the login page has no session,
    and a report the browser cannot deliver measures nothing. So the endpoint is
    bounded instead — one log line per report, each field truncated — and it stores
    nothing, which is what keeps this slice clear of the persistence decision.

    The body is read **from the stream with a limit**, not measured by
    ``Content-Length`` and then parsed: this is a route reached with no session behind
    it, and a chunked request carries no length to measure. So the read itself is what
    refuses an oversized body, rather than a header the sender chooses.
    """
    body = request.stream.read(CSP_REPORT_LIMIT + 1)
    if len(body) > CSP_REPORT_LIMIT:
        logger.warning(
            "csp: a violation report over %d bytes was refused unread",
            CSP_REPORT_LIMIT)
        return "", 204
    # Parsed here rather than through `get_json`, which would read the stream itself:
    # browsers post this as application/csp-report, so there is no content type to
    # negotiate either way.
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        payload = None
    report = payload.get("csp-report") if isinstance(payload, dict) else None
    if not isinstance(report, dict):
        logger.warning("csp: a violation report arrived that was not one")
        return "", 204

    def field(*names: str) -> str:
        """One reported value, from the first name present — flattened and truncated.

        A report is **attacker-influenced text**: a blocked URI is whatever the page
        tried to load. So every control character becomes a space before anything is
        logged, because a newline would otherwise forge a second, arbitrary log line —
        and one line per violation is the whole point of logging them.

        Several names because browsers disagree: `effective-directive` is the current
        field and Safari still sends only the deprecated `violated-directive`.
        """
        for name in names:
            if name in report:
                flat = _CONTROL.sub(" ", str(report[name]))
                return flat[:CSP_FIELD_LIMIT] or "?"
        return "?"

    logger.warning(
        "csp: %s violated on %s — blocked %s (source %s line %s)",
        field("effective-directive", "violated-directive"),
        field("document-uri"), field("blocked-uri"), field("source-file"),
        field("line-number"))
    return "", 204


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
    current = _presentation()
    theme = request.form.get("theme", "")
    layout = request.form.get("layout", "")
    chosen = {
        "theme": theme if theme in THEMES else current["theme"],
        "layout": layout if layout in LAYOUTS else current["layout"],
    }
    response = make_response(redirect(_safe_next(request.form.get("next"))))
    response.set_cookie(PREFS_COOKIE, urlencode(chosen),
                        max_age=PREFS_COOKIE_MAX_AGE, samesite="Lax",
                        secure=_connection_is_secure())
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


@app.template_filter("loaded_from")
def _loaded_from(path: str) -> str:
    """A loaded-from path as `/system` draws it — against the environment or the
    working directory, per :mod:`little_sister.paths`. Both tables that print one
    call this; the origin objects keep the absolute string, and so does the
    `title` the templates hang it in."""
    return shown_path(path)


@app.template_filter("markdown")
def _markdown(text: object) -> Markup:
    """Render a Markdown block to safe HTML (ADR-0018)."""
    return render_markdown(str(text) if text else "")


@app.template_filter("markdown_inline")
def _markdown_inline(text: object) -> Markup:
    """Render Markdown inline (one line, no `<p>`) to safe HTML (ADR-0018)."""
    return render_markdown_inline(str(text) if text else "")


@app.template_filter("node_title")
def _node_title(node: Labeled) -> str:
    """The node's title, or `""` where it only repeats its name (`titles.py`).

    Takes the whole node rather than the title alone, so a template cannot ask
    the question with only half of it. Anything carrying a `name` and a `title`
    answers — a `StatusSnapshot`, a maintenance pin."""
    return shown_title(node.name, node.title)


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
    """A **configured** interval in the units the config wrote it in — 900 is
    `15m` — as :func:`little_sister.spans.format_duration` writes it.

    A name for the template, not a second implementation; the same relationship
    `elapsed` has to `format_span`. The copy document states a check's frequency
    too, and two implementations of *how this project writes an interval* is
    precisely the drift `spans.py` exists to prevent."""
    return format_duration(seconds)


@app.template_filter("elapsed")
def _elapsed(seconds: float | None) -> str:
    """A measured span — a check runtime, a countdown, an uptime — as
    :func:`little_sister.spans.format_span` writes it: ``412 ms``, ``3.1 s``,
    ``43 s``, ``1m 55s``, ``2h 7m``, ``1d 3h``; ``—`` before the first run.

    The filter is a name for the template, not a second implementation: the
    rendering itself is on the public API surface so a check type writing a
    duration into a reason line matches the page it renders onto."""
    return format_span(seconds)


def _format_local(moment: datetime, fmt: str | None = None) -> str:
    """Format a datetime in the configured timezone and ``time_format``
    (config/settings.yaml); ``fmt`` overrides the format (never the timezone) for
    dense spots like the system table's time-of-day cells.

    The one place display timestamps are formatted, so the dashboard's poll
    stamp (served in the ``X-Rendered-At`` response header) matches every
    server-rendered time (ADR-0006) rather than the browser's locale.

    A **copied** document is the one thing formatted elsewhere, by
    :class:`~little_sister.copy_status.TimeStyle` (:func:`_copy_style` builds it
    from this same configuration). Not a second implementation of this one: it
    answers a different question, because it is read where the configured zone is
    not the reader's, so it names the offset this deliberately does not.

    The rendering itself is :func:`little_sister.spans.local_time`, on the public
    surface beside the three spans, so a plugin writing an instant into a line says
    it in the page's own words; this is the name the templates know.
    """
    return local_time(moment, fmt)


def _copy_style() -> TimeStyle:
    """The clock a copy document is written with: this deployment's zone and
    format, resolved once per document so one hand-off cannot straddle a reload."""
    return TimeStyle(config.tzinfo, config.time_format)


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
        # A title that only repeats the name is dropped here as on the chip that
        # opens the card (`titles.py`) — otherwise hovering `critical` pops a card
        # whose entire content is the word *Critical*. A node left with no metadata
        # at all falls out of the map, and gets no hover card, which is right.
        # And a title with no word in it is drawn **with** its name rather than
        # instead of it (ADR-0061): this card has no name of its own, so a band
        # titled 🔴 would head a card with a bare circle. `plain` because a name is
        # structural data and this string is about to be rendered as Markdown.
        name, title = label_parts(current.name, current.title)
        if title:
            label = f"{plain(name)} {title}" if name else title
            meta["title"] = str(render_markdown_inline(label))
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

    ``slot`` places a node's pins: its own first (``-1``), then its entries in the
    **check's** order, which is information (severity, API order) that sorting by an
    opaque slug would scramble. It is a position *within one node*, and so is not
    the node's ``order`` — the sibling rank of ADR-0055, which this object does not
    carry although it is otherwise :class:`~little_sister.titles.Labeled`.

    ``total`` is how many reasons the node had when this
    was read, carried so the popover can say *3 of 20* without a second walk, and
    ``expires_at`` so it can pick the soonest of several without re-parsing a
    humanized string.

    Both authorships travel (ADR-0014) because the two readings differ by
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
    #: Where this pin sits **among the pins of its own node** — the index of the
    #: reason line it covers, and ``-1`` for the node's own pin so that one sorts
    #: first. Deliberately *not* called `order`: since ADR-0055 that word means a
    #: node's declared rank among its **siblings**, and this object is `Labeled`,
    #: so the two would sit one attribute apart with different meanings.
    slot: int = -1
    total: int = 0
    expires_at: str = ""
    set_by: str = ""
    set_at: str = ""
    created_by: str = ""
    created_at: str = ""

    @property
    def name(self) -> str:
        """The pinned node's own name — the last segment of its path. The table
        prints the whole path, whose tail *is* the name, so a title repeating it
        duplicates on this page exactly as it does on a chip; this is what lets
        the `node_title` filter ask the question here too (`titles.py`)."""
        return self.path.rsplit("/", 1)[-1]

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
    return coarse_span(total)


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
    return f"> {coarse_span(elapsed)} ago"


def _pin_view(node: StatusSnapshot, entry: MaintenanceEntry, now: datetime, *,
              slug: str = "", line: str = "", slot: int = -1) -> _MaintenancePin:
    """One stored pin as an index row. ``slug`` / ``line`` / ``slot`` are set for an
    **entry** pin and left at their defaults for a node's own."""
    try:
        remaining = (datetime.fromisoformat(entry.expires_at) - now).total_seconds()
    except ValueError:
        remaining = 0.0
    return _MaintenancePin(
        path=node.path, title=node.title, note=entry.reason,
        remaining=_humanize_remaining(remaining), slug=slug, line=line, slot=slot,
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
        for slot, reason_line in enumerate(current.reasons):
            if reason_line.maintenance is not None:
                here = True
                entry_pins.append(_pin_view(
                    current, reason_line.maintenance, now, slug=reason_line.slug,
                    line=reason_line.text, slot=slot))
        if below and entry is None:
            ancestors.add(current.path)
        return below or entry is not None or here

    if node is not None:
        walk(node)
    node_pins.sort(key=lambda pin: pin.path)
    entry_pins.sort(key=lambda pin: (pin.path, pin.slot))
    return node_pins, entry_pins, ancestors


def _maintenance_pins(node_pins: list[_MaintenancePin],
                      entry_pins: list[_MaintenancePin]) -> list[_MaintenancePin]:
    """Every pin in one list for ``/maintenance``: by path, a node's own pin first,
    then its entries in the check's order."""
    return sorted(node_pins + entry_pins, key=lambda pin: (pin.path, pin.slot))


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
# itself be a secret reference (`scheme://address`, ADR-0023) —
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
        self_report.startup.note(
            "secret-key",
            plain(f"the SECRET_KEY reference did not resolve ({error}); a random "
                  f"per-start key is in use, so every session ends at the next "
                  f"restart"))
        return token_hex(32)
    if key:
        return key
    logger.info("SECRET_KEY not set; using a random per-start key — "
                "sessions reset on restart.")
    return token_hex(32)


app.secret_key = _session_key()


class _TransportSecureSession(SecureCookieSessionInterface):
    """Mark the session cookie ``Secure`` when the connection was (ADR-0065).

    Flask reads a fixed ``SESSION_COOKIE_SECURE`` here, which is a second copy of
    something the transport already knows — and the copy is the one that goes wrong: a
    deployment that sets it and then starts without TLS locks itself out of its own
    login page, with nothing on the screen saying why. So the connection decides.

    An explicitly configured ``True`` still wins, because that is Flask's own setting
    and a deployment that turned it on meant it. There is deliberately no way to turn
    the flag *off* for a TLS connection: the cookie carries a login, and a library
    that can be told to hand one out in the clear eventually is.
    """

    def get_cookie_secure(self, app: Flask) -> bool:
        return bool(app.config["SESSION_COOKIE_SECURE"]) or _connection_is_secure()


app.session_interface = _TransportSecureSession()

# `SameSite=Lax` on the one cookie that carries a login. Flask leaves this unset, which
# hands the decision to whatever the browser defaults to this year — and it was the one
# cookie left to a default, while `ls_prefs` and the fold-depth cookie, which carry a
# theme and a disclosure state, both say `Lax` explicitly (ADR-0028). That is the wrong
# way round on an application whose state-changing POSTs — set and clear maintenance —
# carry no CSRF token: `Lax` is what withholds this cookie from a cross-site form post,
# which is the whole of that attack.
#
# `Lax` rather than `Strict` because a door's **callback** is a top-level navigation
# back from an identity provider (ADR-0069 §4) and `Strict` would drop the cookie on
# arrival, breaking the redirect flow this seam exists to allow. That callback is a GET
# by contract, which is exactly what `Lax` still sends — a provider wanting an OIDC
# `form_post` response mode would need something else, and does not have a route here.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# The retired single-file user override (ADR-0046). A hard cut: the name is never
# honored again, and `users.py` does not know it ever existed. It is read here, once,
# for the opposite purpose — to **refuse**. ADR-0031 §7 retired LITTLE_SISTER_CHECKS_DIR
# by never reading it at all, which was right there because that removal announced
# itself (no checks, no start); this one would not. A deployment that upgrades with the
# variable still set in its unit file, and a user list also in its configuration tree,
# would come up looking healthy while authenticating against a *different* list.
RETIRED_USERS_ENV = "LITTLE_SISTER_USERS"


def _refuse_retired_users_override() -> None:
    """Stop the process while the retired user-list variable is set (ADR-0046)."""
    if not os.environ.get(RETIRED_USERS_ENV):
        return
    raise fatal(
        f"{RETIRED_USERS_ENV} is set, but it is no longer read (ADR-0046) — the user "
        f"list comes from the {CONFIG_DIR_ENV} roots only. Move that file into a "
        f"configuration root and name the root first, e.g. "
        f"{CONFIG_DIR_ENV}=/etc/little-sister/identity:config, then unset "
        f"{RETIRED_USERS_ENV}. Refusing rather than ignoring it: the two can name "
        f"different user lists, and starting on the wrong one is silent.")


# Who may sign in — and **nothing here decides it**. Every door an installation has,
# its own import-before-app block registered (ADR-0069 §2 and §3),
# including the built-in login list, which is `local_login.use_local()` in a `wsgi.py`
# and no longer something this import adds on a deployment's behalf. So all that is
# left to do at this point is to say what was registered, and to warn where the answer
# is *nothing* — an omission logs, only a contradiction refuses.
#
# The `users` aspect is therefore read by `use_local()` rather than here, which is what
# lets a deployment with a provider of its own carry no user list at all. When it is
# read it comes from the configuration path-list in either legal form
# (ADR-0046/0031/0045) and is the one aspect that does **not** merge across roots: the
# first root declaring it wins whole, because merging identities across layers is a
# security question wearing a convenience costume. That rule is also what retired the
# single-file override above.
_refuse_retired_users_override()
identity.announce_doors()

# The same moment, asked about `config/` instead of about the doors. Every aspect any
# of those registrations declared is now in the table, so a candidate file matching none
# of them is genuinely unclaimed and can be named as such — with the packages that read
# the rest, which is what makes a near-miss spelling obvious. This is the *only* place
# the report is emitted: resolving a configuration root is silent, because the first
# resolution in this process is somebody's registration reading its own aspect, and
# every aspect registered after it would have been called unknown for the life of the
# process (ADR-0070).
announce_aspects()

# API tokens for the JSON backend (ADR-0008): "name=token,name2=token2" — set
# directly, or as a value that is itself a secret reference (ADR-0023).
# Unresolvable ⇒ no tokens (the API rejects all requests until restart)
# rather than a crash-loop; a malformed reference still fails startup loudly.
def _api_token_setting() -> str:
    try:
        return resolve_setting(os.environ.get("LITTLE_SISTER_API_TOKENS", ""))
    except SecretError as error:
        self_report.startup.note(
            "api-tokens",
            plain(f"the LITTLE_SISTER_API_TOKENS reference did not resolve "
                  f"({error}); the JSON API rejects every request until a restart"))
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
#: The state layer this process runs on (ADR-0071), kept here so an action on a
#: ``/little-sister`` child can be followed by a flush (ADR-0076 decision 6);
#: ``None`` where no engine runs, which is also every test that does not set one.
state_layer: StateLayer | None = None


def _start_engine_once() -> None:
    global engine, engine_error, state_layer
    if engine is not None:
        return
    if os.environ.get("LITTLE_SISTER_ENGINE", "1").lower() in ("0", "false", "no"):
        logger.info("engine disabled via LITTLE_SISTER_ENGINE")
        return
    state = state_layer = StateLayer(interval_seconds=config.state_interval)
    try:
        engine = create_engine(state=state)
    except CheckError as error:
        engine_error = str(error)
        # Log only, on purpose: with no engine there is no tick to read a
        # self-report line on, and the dashboard's stale beat is the report.
        logger.warning("engine not started: %s", error)
        return
    _restore_state(engine, state)
    _seed_node_metadata(engine)
    engine.start()
    atexit.register(engine.stop)


@app.context_processor
def _inject_engine_error() -> dict[str, str | None]:
    """Expose :data:`engine_error` to every template, so the shared header
    partial can render its engine-not-started alert without per-route plumbing.
    (The login page does not include the header, so nothing leaks pre-login.)"""
    return {"engine_error": engine_error}


@app.context_processor
def _inject_is_admin() -> dict[str, bool]:
    """Expose the current identity's role to every template (ADR-0068).

    The shared header partial draws the nav, and the nav has one admin-only entry.
    It read ``session['admin']`` directly to decide, because most of the pages that
    include the header do not pass a role of their own — which left the last copy of
    *who is this request* outside :mod:`little_sister.identity` after the gate was
    deduplicated into one place. It is not merely a duplicate: an identity that does
    not come from this session would leave the nav silently short an entry while the
    page behind it, gated on the same role, stayed reachable.

    A view that passes ``is_admin`` explicitly still wins — Flask applies the render
    arguments over the context processors — and passes the same value from the same
    place.
    """
    user = identity.current_user()
    return {"is_admin": user is not None and user.admin}


#: Everything ``/health`` may say about the engine — a **closed vocabulary**, and that
#: is the point rather than a tidiness (ADR-0066). The reason an engine did not start
#: is a :class:`~little_sister.checks.CheckError` message that can name a config file
#: or a check, and this is the one route that answers before anybody has logged in.
ENGINE_STATES = ("running", "disabled", "failed")


def _engine_state() -> str:
    """This process's engine, as one word from :data:`ENGINE_STATES` (ADR-0066).

    ``disabled`` and ``failed`` are both "no engine" and are deliberately not one
    word: the first is a deployment saying ``LITTLE_SISTER_ENGINE=0`` and getting
    exactly what it asked for, the second is a configuration this instance could not
    load. Reporting them the same would make a deliberate quiet indistinguishable
    from a broken one, which is the confusion this whole application exists to remove.
    """
    if engine is not None:
        return "running"
    return "failed" if engine_error is not None else "disabled"


@app.route("/health")
def health() -> ResponseReturnValue:
    """Answer *should traffic go here* for something that is not a person (ADR-0066).

    **Liveness, and deliberately not readiness.** ``200`` while this process serves;
    an engine that failed to start does not change the code, because taking the
    instance out of service would take away the very page whose banner explains what
    broke. The engine is *reported* instead, so a probe that wants to alert on it can,
    and one that only routes traffic is not made to care.

    **No login gate**, like ``/csp-report`` and for the same kind of reason: a load
    balancer presents no session and no bearer token, and a health check it cannot
    deliver measures nothing. What that costs is bounded by saying almost nothing —
    two fields, one of them from a closed vocabulary. The version, the configuration
    and the reason an engine did not start are all absent on purpose; they are on the
    pages behind the login, where the reader has already said who they are.

    ``no-store`` because a cached health answer is a lie with a delay on it.
    """
    response = jsonify(status="ok", engine=_engine_state())
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/ready")
def ready() -> ResponseReturnValue:
    """Answer *has this instance finished coming up* — the other half of the
    question ``/health`` deliberately does not answer (ADR-0073).

    **Readiness, and it latches.** ``200`` once an identity door is registered,
    the machine's trust store holds CA certificates and the engine has run every
    check once; ``503`` with the words it is waiting for until then. All three are
    startup facts, so this route goes ``503`` to ``200`` exactly once and never
    back: a later failure can never withdraw a serving instance, which is what
    would remove the very dashboard whose banner explains it (ADR-0066 §1).

    **No login gate**, like ``/health`` and ``/csp-report``, so what it says is
    said to whoever can reach the port. The bound is the closed vocabulary
    (:data:`little_sister.readiness.WAITING_FOR`): three words that name nothing
    about this deployment and answer the one question a caller of an unready
    instance cannot work out for itself — whether to wait or to roll back.

    ``no-store``, for the reason ``/health`` has it.
    """
    answer = instance_readiness.answer()
    payload: dict[str, object] = {"status": readiness.READY}
    if not answer.ready:
        payload = {"status": readiness.NOT_READY,
                   "waiting_for": list(answer.waiting_for)}
    response = jsonify(payload)
    response.status_code = 200 if answer.ready else 503
    response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def _inject_user_avatar() -> dict[str, str]:
    """Give the shared settings trigger the session user's avatar URL.

    The default is a public packaged asset. A custom picture goes through the
    login-gated, username-free route below, so neither the URL nor the template
    exposes the configured user roster (ADR-0045).
    """
    user = identity.current_user()
    if identity.is_system_admin_session():
        # The distinct packaged avatar (ADR-0069 §5), and it comes *first*: the
        # account's name is `admin`, which a deployment's own user list may also
        # have — and the one session that must never wear somebody else's picture
        # is this one.
        return {"user_avatar_url": url_for(
            "static", filename="system-admin-avatar.svg")}
    avatars = local_login.registered_avatars()
    url = (url_for("user_avatar") if user is not None and user.name in avatars
           else url_for("static", filename="default-avatar.svg"))
    return {"user_avatar_url": url}


def _seed_node_metadata(engine: Engine) -> None:
    """Resolve `about` (nodes.yaml > inline check), seed it onto the tree, and run
    the startup consistency pass (ADR-0012). A bad `nodes.yaml` is logged, not
    fatal — node metadata must not stop monitoring."""
    try:
        metadata = resolve_metadata(engine.checks, load_nodes())
    except CheckError as error:
        self_report.startup.note(
            "nodes",
            plain(f"nodes.yaml was not loaded ({error}); every node shows what its "
                  f"check says and none of the metadata written there"))
        return
    for path, meta in metadata.items():
        status_tree.set_about(path, meta.about)
        status_tree.set_title(path, meta.title)
        # Only where the entry states one: seeding `None` as `0` would make every
        # nodes.yaml entry an ordering declaration and shut out the check's rank
        # on any node that merely has an `about` (ADR-0055).
        if meta.order is not None:
            status_tree.set_order(path, meta.order)
        # Likewise, and for the sharper case: a `false` here is a deployment
        # declining a claim a check type ships, so it has to occupy the field —
        # while seeding `None` as `False` would make every nodes.yaml entry a
        # declaration and shut out the check on any node that merely has an
        # `about` (ADR-0063).
        if meta.show_when_quiet is not None:
            status_tree.set_show_when_quiet(path, meta.show_when_quiet)
    run_consistency_pass(engine.checks, metadata)


def _restore_state(engine: Engine, state: StateLayer) -> None:
    """Initialize the tree with what the state layer kept (ADR-0071) — once,
    post-fork before the engine runs.

    **The keeper first, before any of it** (ADR-0071 §5): an instance whose
    deployment registered one is restored from the copies it holds, so a fresh
    machine comes up as the instance that stopped on the old one. With no keeper —
    a local installation — it is a no-op, and with one that cannot be reached the
    local files stand and the failure is a line.

    Then the event log: put back what the last process wrote, so the events page
    and every node's history start where they left off, and register the log as a
    kept file so this process writes it on the tick. Then maintenance: attach the
    store, replay non-expired pins — whose transitions append to the restored log,
    as this process's first events — and reap any whose path no configured check
    covers (ADR-0014). The layer itself is the first self-report contributor: a
    load that failed here, or a save that fails later, is a line on the heartbeat.
    A failure never refuses to start — the layer reports it and the state starts
    empty.

    Each of the two files is registered with its other direction too — the
    ``restore`` an adoption hands the store's copy to when a keeper's tick makes
    this instance the holder, or the backup's on *take the backups* (ADR-0077):
    the tree's ``adopt_events`` beside the log's producer, and the side-table's,
    which ``MaintenanceStore`` registers itself at construction. The log first,
    because the pins' adoption writes its transitions into the log and files are
    adopted in registration order. *Take the backups* is the layer's one action
    on its child, admin-only like every write.
    """
    state.restore_from_keeper()
    state.take_stock()
    payload = state.read(EVENTS_FILE)
    if payload is not None:
        try:
            restored = status_tree.restore_events(events_from_payload(payload))
        except ValueError as error:
            state.report_load_failure(EVENTS_FILE, str(error))
        else:
            logger.info("state: restored %d event(s) from %s", restored,
                        state.path(EVENTS_FILE))
    state.keep(EVENTS_FILE, status_tree.events_payload,
               restore=status_tree.adopt_events)
    store = MaintenanceStore(state, tree=status_tree)
    status_tree.use_maintenance_store(store)
    nodes, entry_pins = store.load_all()
    status_tree.restore_maintenance(nodes, entry_pins=entry_pins)
    reaped = status_tree.reap_uncovered(engine.check_roots())
    if reaped:
        logger.info("maintenance: reaped %d orphaned pin(s): %s",
                    len(reaped), ", ".join(sorted(reaped)))
    self_report.register_contributor(
        "state", state.lines, title="State", report=state.report,
        about="What a restart keeps — the maintenance pins and the event log under "
              "`var/state/` — and whether it was restored, written and, where a "
              "keeper is registered, carried off the machine (ADR-0071); and what "
              "a takeover set aside as `.bak`, which *take the backups* swaps back "
              "(ADR-0077).")
    self_report.register_action("state", "take-backups", "Take the backups",
                                state.take_backups)


_start_engine_once()


#: The machine's trust store, counted **once** here and never again (ADR-0073).
#: It is the one thing in the readiness answer that touches the machine, and a
#: report on the seam is recorded state rather than a probe (ADR-0072), so the
#: measurement happens at startup and everything afterwards reads this.
trust_store = readiness.measure_trust_store()


def _first_pass_done() -> bool:
    """Whether there is a first pass to wait for and the engine has finished it.

    The two ways to have no engine are not one answer (ADR-0066 §2 draws the same
    line for ``/health``). A deployment that said ``LITTLE_SISTER_ENGINE=0`` has
    **no pass to wait for** and is ready at once — a deliberate quiet is not a
    thing to keep traffic away from. A configuration this instance could not load
    leaves an engine that will never run one, and that instance never becomes
    ready: it serves, its banner explains itself to whoever opens it, and a
    balancer with a working instance beside this one sends traffic there.
    """
    if engine is not None:
        return engine.outcomes.first_pass
    return engine_error is None


def _check_outcomes() -> readiness.Outcomes | None:
    """What the engine's checks last stored, or ``None`` where no engine runs —
    an instance with no engine makes no claim about checks it is not running."""
    return engine.outcomes if engine is not None else None


#: This instance's readiness (ADR-0073), and the contributor that carries its two
#: lines to ``/little-sister``. Registered here rather than in the
#: import-before-app block because two of the three conditions are only settled
#: once that block and the engine start have both run.
instance_readiness = readiness.Readiness(
    doors=lambda: bool(identity.registered_doors()),
    trust=lambda: trust_store,
    first_pass=_first_pass_done,
    outcomes=_check_outcomes)
self_report.register_contributor(
    "readiness", instance_readiness.lines, title="Readiness",
    about="Whether this instance can be sent traffic — what `/ready` answers, and "
          "the two silent failures of a first rollout as lines (ADR-0073).")
# What this process learned at startup and cannot undo — a setting it could not
# honor, a door that is shut — noted into `self_report.startup` wherever it was
# learned, and read here under one name (ADR-0072 §7).
self_report.register_contributor(
    "startup", self_report.startup.lines, title="Startup",
    about="What this process learned at startup and cannot undo until a restart: a "
          "setting it could not honor, a credential reference that did not resolve, "
          "a door nobody can enter, a file no aspect claims. Each line stands for the "
          "life of the process and is also the log entry it used to be.")
# What recurs at runtime, and what touches security, each held for a window
# after it was last seen (ADR-0072 §7): the line stands while the condition does.
self_report.register_contributor(
    "runtime", self_report.runtime.lines, title="Runtime",
    about="What keeps going wrong while this process runs — a renderer that raises, "
          "a probe that fails, a tick that did not land — each held ten minutes "
          "after it was last seen, counted rather than repeated.")
self_report.register_contributor(
    "security", self_report.security_lines, title="Security",
    report=self_report.security_report,
    about="Failed logins as a rate — a fact in the report below five in ten "
          "minutes, a warning from five — and the system-admin account when it is "
          "used.")


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


@app.before_request
def _require_identity() -> ResponseReturnValue | None:
    """Refuse a request with no identity, unless its endpoint says otherwise.

    **The whole login gate, in one place and refusing by default** — a route added
    tomorrow is closed until its endpoint is put on one of the two lists in
    :mod:`little_sister.identity`, which is an edit somebody has to justify rather than
    a check somebody has to remember. It replaced the same two lines, in thirteen views.
    """
    if identity.needs_identity(request.endpoint) and identity.current_user() is None:
        return identity.challenge()
    return None


@app.route('/')
def index() -> ResponseReturnValue:
    return redirect("/status")


@app.route('/login', methods=['GET', 'POST'])
def login() -> ResponseReturnValue:
    """The way in, at the address every install has: the **default door's** login
    step, whichever door that is (ADR-0069 §4). On an install that registered the
    built-in login list that is :mod:`little_sister.local_login`, which is a door
    like any other — and a ``404`` on one that registered no default at all, which
    is a state an installation is allowed to start in."""
    return identity.login_response()


@app.route('/login/<door>', methods=['GET', 'POST'])
def login_door(door: str) -> ResponseReturnValue:
    """One door's own login step — the address that stays a local form under a
    provider that redirects, and the reason a way in can be kept for the morning the
    identity provider is the thing that broke (ADR-0069 §2)."""
    return identity.login_response(door)


@app.route('/auth/callback/<door>')
def login_callback(door: str) -> ResponseReturnValue:
    """Where a door's redirect flow comes back to (ADR-0069 §4)."""
    return identity.callback_response(door)


@app.route('/logout')
def logout() -> ResponseReturnValue:
    return identity.logout_response()


def _split_heartbeat(
    node: StatusSnapshot | None,
) -> tuple[StatusSnapshot | None, StatusSnapshot | None]:
    """Lift the engine's self-heartbeat (ADR-0005) out of a root snapshot's
    children so the dashboard can render it as the status strip (ADR-0024) rather than
    a grid card. Returns ``(node_without_heartbeat, heartbeat)``.

    The heartbeat is only ever a child of the root overview, so on a branch page
    (or when the engine is disabled) this returns ``node`` unchanged with
    ``None``. The heartbeat is a **branch** — one child per contributor
    (ADR-0076) — and the strip is its roll-up: it summarizes the subtree the way
    any branch card does and links to it, so nothing is hidden by lifting it.
    Splitting happens before the hide-ok/hide-idle filter, so the strip stays
    visible regardless of the filters. The JSON API is untouched: it serialises
    the whole snapshot upstream of this call.
    """
    if node is None:
        return None, None
    heartbeat: StatusSnapshot | None = None
    kept: list[StatusSnapshot] = []
    for child in node.children:
        if child.path == HEARTBEAT_PATH:
            heartbeat = child
        else:
            kept.append(child)
    if heartbeat is None:
        return node, None
    return replace(node, children=tuple(kept)), heartbeat


@app.route('/status')
@app.route('/status/<path:branch>')
def status(branch: str = "") -> ResponseReturnValue:
    # JSON backend mode (ADR-0080): content-negotiated, token-gated, read-only.
    if request.accept_mimetypes.best_match(
            ("text/html", "application/json")) == "application/json":
        if authenticate(request.headers.get("Authorization"), api_tokens) is None:
            return _api_problem(401, "Unauthorized",
                                "A valid bearer token is required.")
        node = status_tree.snapshot(branch)
        if node is None:
            return _api_problem(404, "Not Found",
                                f"No status node at path {branch!r}.")
        # The two facts `/health` withholds from an ungated caller are fine
        # here, where the reader has already presented a token (ADR-0080).
        return _api_json(status_envelope(node, version=__version__,
                                         engine=_engine_state()))
    # This route is not behind the gate (`identity.SELF_AUTHENTICATING_ENDPOINTS`):
    # the JSON branch above answers a bearer token, and a gate in front of the whole
    # view would redirect an API client to a login form. So the session half is
    # checked here, after the negotiation that decides which credential applies.
    user = identity.current_user()
    if user is None:
        return identity.challenge()
    node = status_tree.snapshot(branch)
    # A leaf node (a check) gets its own detail page.
    if branch and node is not None and not node.children:
        # The current period's start — or None when this node has no transition of its
        # own to bound one, in which case the page reports the single observation
        # instead of a from/until of one instant (ADR-0027).
        since = _since_of(branch)
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
        # The hand-off, from the **same** snapshot the page renders: one node
        # cannot be described two ways in one response, and the rich HTML comes
        # from the canonical Markdown rather than beside it, so the two clipboard
        # members cannot drift (the `/copy` rule, one node down).
        copy_markdown = format_node_markdown(node, _copy_style(), since)
        copy_rich = render_markdown(copy_markdown)
        return render_template('check.html', username=user.name,
                               firstname=user.firstname, node=node,
                               branch=branch, since=since, focus=focus,
                               focus_orphan=focus_orphan,
                               is_admin=user.admin,
                               maintenance_default=config.maintenance_default_expiry,
                               maintenance_timezone=config.timezone,
                               copy_markdown=copy_markdown,
                               copy_html_text=str(copy_rich))
    # A branch page renders the same node-facts block as the leaf page (ADR-0044
    # decision 8), so it needs the same `since`: the start of the node's current
    # **own**-status period, from its own transition log — a container has one of
    # those like any other node, which is half of why the block can be shared.
    # None on the overview root, which is nobody's node.
    branch_periods = status_tree.history(branch) if branch and node else []
    since = branch_periods[-1].since if branch_periods else None
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
    # reads the same clock — "updated …" / "could not refresh — last ok …" honor
    # settings.yaml's time_format and timezone, not the browser's locale.
    rendered_at = _format_local(now)
    if request.args.get('fragment'):
        body = render_template('_status_grid.html', node=node, branch=branch,
                               since=since,
                               max_depth=depth, hide_ok=hide_ok,
                               hide_idle=hide_idle, dense=dense,
                               is_admin=user.admin,
                               heartbeat=heartbeat, reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_rows=maintenance_rows,
                               maintenance_ancestors=maintenance_ancestors)
    else:
        # The hover card (ADR-0019) must know the strip too: the lifted
        # heartbeat's nodes.yaml title/about join the map like any node's.
        node_meta = _node_meta_map(node) | _node_meta_map(heartbeat)
        body = render_template('status.html', username=user.name,
                               firstname=user.firstname, node=node,
                               branch=branch, since=since, max_depth=depth,
                               depth_limit=MAX_DEPTH, hide_ok=hide_ok,
                               hide_idle=hide_idle, dense=dense,
                               is_admin=user.admin,
                               maintenance_default=config.maintenance_default_expiry,
                               maintenance_timezone=config.timezone,
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
                                max_age=VIEW_COOKIE_MAX_AGE, samesite='Lax',
                                secure=_connection_is_secure())
        for name, value in (('hide_ok', hide_ok), ('hide_idle', hide_idle),
                            ('dense', dense)):
            if request.args.getlist(name) or request.args.get('view'):
                response.set_cookie(name, '1' if value else '0',
                                    max_age=VIEW_COOKIE_MAX_AGE, samesite='Lax',
                                    secure=_connection_is_secure())
    return response


@app.route('/history/<path:path>')
def history(path: str) -> ResponseReturnValue:
    user = identity.signed_in()
    node = status_tree.snapshot(path)
    periods = list(reversed(status_tree.history(path)))
    return render_template('history.html', username=user.name,
                           firstname=user.firstname, node=node,
                           branch=path, periods=periods)


_DEFAULT_MAINTENANCE_SECONDS = 7 * 24 * 3600   # hard fallback if config is unusable

# A maintenance window has to be a **positive** number of seconds, and a bounded one
# (ADR-0014). ADR-0014 promised a *finite* expiry; finite was never enough:
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


class _BadExpiry(Exception):
    """An expiry the maintenance form cannot resolve safely. Carries the sentence
    the refusal page shows."""


_FULL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FULL_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?"
    r"(?:[zZ]|[+-]\d{2}:\d{2})?$")
_MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")
_CLOCK = re.compile(r"^(\d{2}):(\d{2})$")
_WEEKDAY_CLOCK = re.compile(
    r"^(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\s+(\d{2}):(\d{2})$",
    re.IGNORECASE)
_WEEKDAY = re.compile(
    r"^(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)$",
    re.IGNORECASE)
_WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def _expiry_help(text: str) -> _BadExpiry:
    return _BadExpiry(
        f"{text!r} is not a duration or expiry. Use 2h, 1w, 17s, "
        f"2026-07-10 18:00, 07-10, 17, 18:00, Friday or Fri 18:00. "
        f"Times without an offset use {config.timezone}.")


@dataclass(frozen=True)
class _IntervalFloor:
    """The slowest check a pin covers — how often it runs and where it sits — which
    is the least a window has to last to cover one run of everything the pin
    names (ADR-0014)."""
    seconds: int
    path: str


def _interval_floor(path: str) -> _IntervalFloor | None:
    """The floor for a pin at ``path``: the longest ``frequency`` among the checks
    that cover it — on the same root-to-leaf line, exactly the reaper's reading
    of *covers* — because a window shorter than that ends before one of the
    checks it silences runs again. ``None`` where the app cannot see the checks
    (no engine, as in the tests) or none covers the path; the one-second floor
    of decision 13 stays there. A check that runs less often than the one-year
    ceiling could never be covered at all, so it sets no floor either.
    """
    if engine is None:
        return None
    slowest: _IntervalFloor | None = None
    for check in engine.checks:
        seconds = check.frequency_seconds
        if seconds <= 0 or not on_same_line(path, check.path):
            continue
        if slowest is None or seconds > slowest.seconds:
            slowest = _IntervalFloor(seconds, check.path)
    if slowest is not None and slowest.seconds > MAX_MAINTENANCE_SECONDS:
        return None
    return slowest


def _above_the_floor(seconds: float, source: str,
                     floor: _IntervalFloor | None) -> None:
    """Refuse a window that ends before the slowest covered check runs again. It
    reads the **resolved** window, so ``18:00`` typed at 17:59 is measured the
    same way as ``60s`` — the spelling is not what makes a window pointless."""
    if floor is not None and seconds < floor.seconds:
        interval = format_duration(floor.seconds)
        raise _BadExpiry(
            f"{source!r} ends before {floor.path} (every {interval}) runs "
            f"again, so the pin would cover no run of it. Use at least "
            f"{interval}.")


def _server_local(moment: datetime) -> datetime:
    """The existing timestamp convention: naive server-local (ADR-0006). Calling
    ``astimezone`` without an argument converts at *moment*, including a DST change
    between now and the expiry, rather than retaining today's fixed UTC offset."""
    return moment.astimezone().replace(tzinfo=None)


def _configured_wall_time(wall: datetime, source: str) -> datetime:
    """Attach the configured timezone to one naive wall time, refusing both holes
    and folds. ``zoneinfo`` accepts either silently; round-tripping both folds via
    UTC tells a normal instant (one unique result) from a missing one (none) and an
    ambiguous one (two). An explicit offset never comes through this function."""
    choices: dict[datetime, datetime] = {}
    for fold in (0, 1):
        aware = wall.replace(tzinfo=config.tzinfo, fold=fold)
        round_trip = aware.astimezone(UTC).astimezone(config.tzinfo)
        if round_trip.replace(tzinfo=None) == wall:
            choices[aware.astimezone(UTC)] = aware
    if len(choices) != 1:
        raise _BadExpiry(
            f"{source!r} is not an unambiguous local time in {config.timezone}. "
            f"Use an explicit UTC offset for a clock change.")
    return next(iter(choices.values()))


def _wall(year: int, month: int, day: int, hour: int = 0,
          minute: int = 0, second: int = 0) -> datetime | None:
    """Build a calendar wall time, or ``None`` for a date/time that does not
    exist. Calendar absence is distinct from a DST hole, which is diagnosed after
    a valid wall time has been built."""
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _next_month_day(month: int, day: int, now: datetime,
                    source: str) -> datetime:
    local_now = now.astimezone(config.tzinfo)
    # Eight years covers two leap-day opportunities. The one-year guard below will
    # refuse a distant result; the wider search lets it report the range rather than
    # pretending 02-29 is malformed.
    for year in range(local_now.year, local_now.year + 9):
        wall = _wall(year, month, day)
        if wall is None:
            continue
        candidate = _configured_wall_time(wall, source)
        if candidate.astimezone(UTC) > now:
            return candidate
    raise _expiry_help(source)


def _next_day_of_month(day: int, now: datetime, source: str) -> datetime:
    local_now = now.astimezone(config.tzinfo)
    year, month = local_now.year, local_now.month
    # A numbered day recurs within two months, but twelve keeps this helper plain
    # and makes the no-clamping rule obvious.
    for _ in range(12):
        wall = _wall(year, month, day)
        if wall is not None:
            candidate = _configured_wall_time(wall, source)
            if candidate.astimezone(UTC) > now:
                return candidate
        month += 1
        if month == 13:
            year += 1
            month = 1
    raise _expiry_help(source)


def _clock_candidate(hour: int, minute: int, now: datetime,
                     source: str) -> datetime:
    local_now = now.astimezone(config.tzinfo)
    wall = _wall(local_now.year, local_now.month, local_now.day, hour, minute)
    if wall is None:
        raise _expiry_help(source)
    candidate = _configured_wall_time(wall, source)
    if candidate.astimezone(UTC) <= now:
        tomorrow = local_now.date() + timedelta(days=1)
        wall = _wall(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute)
        assert wall is not None
        candidate = _configured_wall_time(wall, source)
    return candidate


def _weekday_candidate(weekday: int, hour: int, minute: int, now: datetime,
                       source: str, *, allow_today: bool = True) -> datetime:
    local_now = now.astimezone(config.tzinfo)
    days = (weekday - local_now.weekday()) % 7
    if days == 0 and not allow_today:
        days = 7
    wanted = local_now.date() + timedelta(days=days)
    wall = _wall(wanted.year, wanted.month, wanted.day, hour, minute)
    if wall is None:
        raise _expiry_help(source)
    candidate = _configured_wall_time(wall, source)
    if candidate.astimezone(UTC) <= now:
        wanted += timedelta(days=7)
        wall = _wall(wanted.year, wanted.month, wanted.day, hour, minute)
        assert wall is not None
        candidate = _configured_wall_time(wall, source)
    return candidate


def _bounded_expiry(candidate: datetime, now: datetime, source: str,
                    floor: _IntervalFloor | None = None) -> datetime:
    seconds = (candidate.astimezone(UTC) - now).total_seconds()
    if seconds < MIN_MAINTENANCE_SECONDS:
        raise _BadExpiry(
            f"A maintenance expiry has to be in the future — {source!r} is not.")
    if seconds > MAX_MAINTENANCE_SECONDS:
        raise _BadExpiry(
            f"{source!r} is longer than a year, which is longer than a maintenance "
            f"window is ever meant to be. Pick something sooner.")
    _above_the_floor(seconds, source, floor)
    return _server_local(candidate)


def _duration_expiry(text: str, now: datetime,
                     floor: _IntervalFloor | None = None) -> datetime:
    try:
        seconds = parse_duration(text, _DEFAULT_MAINTENANCE_SECONDS)
    except (CheckError, OverflowError, ValueError) as error:
        # The one refusal with a sentence of its own: `6M` used to lowercase into
        # six *minutes*, and the pin was gone before whoever meant six months
        # looked again. The generic help would list the forms and not say that.
        if text.endswith("M"):
            raise _BadExpiry(
                f"{text!r} — M is not a unit: m is minutes, and a month has no "
                f"fixed length. Write 26w, 180d or a date like 2026-07-10.") from error
        raise _expiry_help(text) from error
    if seconds < MIN_MAINTENANCE_SECONDS:
        raise _BadExpiry(
            f"A maintenance window has to be in the future — {text!r} is not. "
            f"Use 2h, 3d, 90m or explicit seconds such as 17s.")
    if seconds > MAX_MAINTENANCE_SECONDS:
        raise _BadExpiry(
            f"{text!r} is longer than a year, which is longer than a maintenance "
            f"window is ever meant to be. Pick something shorter.")
    _above_the_floor(seconds, text, floor)
    return _server_local(now + timedelta(seconds=seconds))


def _maintenance_expiry(raw: str, *, now: datetime | None = None,
                        floor: _IntervalFloor | None = None) -> datetime:
    """Resolve the maintenance form's duration-or-expiry field (ADR-0014).

    ``now`` is captured once by the route and is always compared as an instant.
    Blank uses the configured *duration* default; it is the one value that falls
    back rather than refusing, so a deployment typo cannot make the form unusable
    — and it is held to no ``floor`` for the same reason. Every explicit value is:
    the resolved window has to reach the slowest covered check's next run
    (:func:`_interval_floor`), whichever spelling produced it. All explicit
    calendar shortcuts are resolved in the configured timezone and the result
    crosses the boundary in the existing naive server-local format.
    """
    instant = now or datetime.now(UTC)
    instant = instant.astimezone(UTC)
    text = raw.strip()
    if not text:
        try:
            fallback = parse_duration(config.maintenance_default_expiry,
                                      _DEFAULT_MAINTENANCE_SECONDS)
        except (CheckError, OverflowError, ValueError):
            fallback = _DEFAULT_MAINTENANCE_SECONDS
        if not MIN_MAINTENANCE_SECONDS <= fallback <= MAX_MAINTENANCE_SECONDS:
            fallback = _DEFAULT_MAINTENANCE_SECONDS
        return _server_local(instant + timedelta(seconds=fallback))

    # A bare integer belongs to the calendar, not to the duration grammar. This
    # is the form's only intentional compatibility cut: write ``17s`` for seconds.
    if text.isdecimal():
        day = int(text)
        if not 1 <= day <= 31:
            raise _expiry_help(text)
        return _bounded_expiry(
            _next_day_of_month(day, instant, text), instant, text, floor)

    # Exactly the unit-suffixed durations the shared parser accepts — its own
    # unit set, so the two cannot drift — and nothing wider: every other spelling
    # below is a calendar form. Routed on the letter whatever its case, so that a
    # capital gets the parser's refusal (`5H`, and `6M` by name) rather than the
    # calendar's.
    if text[-1].lower() in DURATION_UNITS:
        return _duration_expiry(text, instant, floor)

    try:
        if _FULL_DATE.fullmatch(text):
            parsed_date = datetime.fromisoformat(text)
            candidate = _configured_wall_time(parsed_date, text)
        elif _FULL_TIMESTAMP.fullmatch(text):
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text[-1].lower() == "z" else text)
            candidate = (parsed if parsed.tzinfo is not None
                         else _configured_wall_time(parsed, text))
        elif match := _MONTH_DAY.fullmatch(text):
            candidate = _next_month_day(
                int(match.group(1)), int(match.group(2)), instant, text)
        elif match := _CLOCK.fullmatch(text):
            candidate = _clock_candidate(
                int(match.group(1)), int(match.group(2)), instant, text)
        elif match := _WEEKDAY_CLOCK.fullmatch(text):
            candidate = _weekday_candidate(
                _WEEKDAYS[match.group(1).lower()], int(match.group(2)),
                int(match.group(3)), instant, text)
        elif match := _WEEKDAY.fullmatch(text):
            candidate = _weekday_candidate(
                _WEEKDAYS[match.group(1).lower()], 12, 0, instant, text,
                allow_today=False)
        else:
            raise _expiry_help(text)
    except ValueError as error:
        raise _expiry_help(text) from error
    return _bounded_expiry(candidate, instant, text, floor)


@app.route('/little-sister/<contributor>/act/<slug>', methods=['POST'])
def self_report_action(contributor: str, slug: str) -> ResponseReturnValue:
    """Run an action a package offered on its contributor's node (ADR-0076) —
    *take over the lease*, *release it* — for an admin, and come back to the
    node with what it said.

    Gated like every route (identity), admin-only like every write; an action
    nobody registered is a 404, and whatever the handler raises is caught and
    shown as the sentence, because a button that answers with a traceback page
    has told the operator nothing about the thing they pressed it for.

    **An action that ran is followed by a flush of the state layer**: an action
    is a write into this process, and what it changed reaches the store now
    rather than at the next interval — a keeper's *take over* adopts and saves
    in the click, and on an instance that holds the lease already it is the
    save. The flush is the scheduler's own, serialized with it, and never raises;
    a handler that raised changed nothing worth flushing.
    """
    user = identity.signed_in()
    if not user.admin:
        abort(403)
    action = self_report.find_action(contributor, slug)
    if action is None:
        abort(404)
    try:
        said = action.handler() or ""
    except Exception as error:
        logger.exception("self-report: the action %s on %s raised", slug, contributor)
        said = f"{action.label} failed: {error!r}"
    else:
        logger.info("self-report: %s ran %s on %s%s", user.name, slug, contributor,
                    f" — {said}" if said else "")
        if state_layer is not None:
            state_layer.flush()
    if said:
        flash(said)
    return redirect(url_for("status", branch=f"little-sister/{contributor}"))


@app.route('/maintenance', methods=['POST'])
def maintenance() -> ResponseReturnValue:
    """Set, edit or clear a pin — a **compare-and-set** write (ADR-0014).

    Every form here carries the entry's ``set_at`` as a hidden token: the write
    names the pin it believes it is replacing, and an empty token says *"I believe
    nothing is pinned"*. When the table says otherwise the write is refused whole —
    nothing is written — and the admin gets the conflict page with both texts and
    their own words intact. A post with **no** ``set_at`` field at all (a hand-rolled
    client, never one of our forms) writes unguarded, exactly as before.
    """
    user = identity.signed_in()
    if not user.admin:
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
        now = datetime.now(UTC)
        try:
            expires_at = _maintenance_expiry(duration, now=now,
                                             floor=_interval_floor(path))
        except _BadExpiry as bad:
            # Nothing is written and the admin's words come back — the same
            # posture as a refused compare-and-set, for the same reason: a write
            # that silently did something other than what was asked is the thing
            # this route is not allowed to do (ADR-0014).
            return refused(problem=str(bad), stored=None)
        # A blank reason on an **edit** means "I did not touch this field", so the
        # stored text stays; on a new pin there is nothing to keep and the literal
        # `maintenance` is the honest placeholder.
        held = _held_reason(path, slug, token)
        reason = typed or held or 'maintenance'
        setter = (partial(status_tree.set_entry_maintenance, path, slug) if slug
                  else partial(status_tree.set_maintenance, path))
        write = setter(reason, expires_at=expires_at,
                       set_by=user.name,
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
    duration or expiry we will not accept — because the admin's situation is the same.

    On a bad expiry the form carries the **original** token, because nothing about
    the stored pin moved; a refused compare-and-set is the case that needs a
    refreshed one, and that branch reads it off the entry it is showing.
    """
    user = identity.signed_in()
    return render_template(
        'maintenance_conflict.html', username=user.name,
        firstname=user.firstname, path=path, back=back,
        clearing=clearing, stored=stored, slug=slug, problem=problem,
        mine=mine, duration=duration, token=token,
        maintenance_default=config.maintenance_default_expiry,
        maintenance_timezone=config.timezone)


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
    user = identity.signed_in()
    node_pins, entry_pins, _ = _maintenance_view(
        status_tree.snapshot(""), datetime.now())
    return render_template('maintenance.html', username=user.name,
                           firstname=user.firstname,
                           pins=_maintenance_pins(node_pins, entry_pins))


@app.route('/events')
def events() -> ResponseReturnValue:
    user = identity.signed_in()
    recent = list(reversed(status_tree.recent_events()))
    return render_template('events.html', username=user.name,
                           firstname=user.firstname, events=recent)


@dataclass(frozen=True)
class TypeRow:
    """One check type on ``/system``'s roster, with the checks that name it.

    ``paths`` is the node path of every check configured with this type, in the
    engine's own order — so it reads down the page in the same order as the check
    table above it — and one entry per *check*, not per node: two checks may sit on
    one host node (ADR-0015 allows it for disjoint owned subtrees), and a list that
    deduplicated them would stop matching the count it is there to substantiate.
    """
    origin: TypeOrigin
    paths: tuple[str, ...]

    @property
    def count(self) -> int:
        """How many checks name this type — the number the row leads with."""
        return len(self.paths)


def _type_roster(
        info: EngineInfo | None,
) -> tuple[list[TypeRow], list[TypeRow]]:
    """The registered check types, split into the ones this configuration uses and
    the ones it merely could — each carrying the checks that use it (none in the
    second list, which is what the split means).

    Two questions land on this roster and only one of them is urgent. *Which code
    answers for `type: github`, at which version* is a live diagnostic, and it can
    only ever concern the handful of types the configuration actually names. *What
    may I write in my YAML* is discovery: it needs the whole list, but it can wait
    behind a disclosure. So the used types come first, carrying their count, and
    the rest fold away — a card that was mostly rows nobody had asked about.

    The row carries the **paths** rather than the count it is shown as, because a
    count is the one thing on this page that cannot be checked from this page. Two
    of what? — and the configuration naming a type in two different check files,
    each rendering in a different branch of the tree, is the ordinary case, not a
    defect. Everything else on `/system` names its subjects; this row now can too,
    and the paths were in hand all along (`info.checks`). Node paths, not check
    names, because the path is what the reader can go and look at.

    Folded rather than dropped, because the roster is also the only place a freshly
    installed plugin can be seen to have registered *before* any check uses it —
    the same silent failure the extensions card exists to catch. Dropping the
    unused ones would make "installed, registered, waiting" indistinguishable from
    "the entry point never fired". An unused type keeps no list, which is only the
    empty tuple saying what the fold below the table already says.

    With no engine — or an engine with no checks — nothing is known to be in use,
    so the first list is empty and the caller renders the second one flat. That is
    not a fallback so much as the case that most wants the roster: a start refused
    for an unknown `type:` leaves exactly this page with no engine behind it.
    """
    used: dict[str, list[str]] = {}
    for check in (info.checks if info is not None else ()):
        used.setdefault(check.type_name, []).append(check.path)
    in_use = [TypeRow(origin, tuple(used[origin.type_name]))
              for origin in registered_types() if origin.type_name in used]
    folded = [TypeRow(origin, ()) for origin in registered_types()
              if origin.type_name not in used]
    return in_use, folded


@dataclass(frozen=True)
class PackageRow:
    """One package on ``/system``'s inventory, with everything it registered."""
    origin: PackageOrigin
    registers: tuple[str, ...]


def _registering_packages() -> list[PackageRow]:
    """Every package outside the library that registered anything, with where it
    was loaded from and what it contributed.

    A package reaches this instance through five seams — a check type, a slot
    filler, an asset, a configuration aspect, a secret resolver (ADR-0051,
    ADR-0034, ADR-0037, ADR-0035, ADR-0064) — and until this card only the first
    reported a version, because the
    check-type roster is the one that carries an origin. So an extension that
    registers **no check type** was the one thing on the page whose release could
    not be read off the running instance at all: the seam tables name a package and
    stop there. That is the wrong way round — the version is a property of the
    installation, not of the seam it happens to reach us through, and repeating it
    on each seam's rows would print it once per slot for a package that fills two.

    The library itself is left out on purpose: the page header already carries its
    version, and every row here is meant to be something somebody added.
    """
    registers: dict[str, set[str]] = {}
    for origin in registered_types():
        registers.setdefault(origin.package, set()).add(f"type {origin.type_name}")
    # Extension fillers only — the library's own declarative actions fill the same
    # slots through the same seam (ADR-0038) and would put `little_sister` here.
    #
    # A filler names the package its *templates* live under, which may be a
    # submodule (`x.chips`). The row is keyed by the top-level package instead,
    # because an installation is what carries a distribution and a version — one
    # row per install, or a package that registers from two modules gets two rows
    # and neither is the thing that was installed. The seam's own table below keeps
    # printing the name the filler was registered with.
    for filler in slots.extension_fillers():
        registers.setdefault(filler.package.split(".")[0],
                             set()).add(f"slot {filler.slot}")
    for asset in slots.assets():
        registers.setdefault(asset.package.split(".")[0],
                             set()).add(f"asset {asset.member}")
    for aspect in registered_aspects():
        # An aspect whose registrant could not be inferred is left unattributed
        # here rather than guessed; the extensions card still lists the name.
        if owner := aspect_owner(aspect):
            registers.setdefault(owner, set()).add(f"config/{aspect}")
    for registration in registered_resolvers():
        # Same rule: a resolver registered from `__main__` names no installation,
        # so there is no row it could honestly join. The scheme list below still
        # shows it, where the row is the scheme rather than the package.
        if registration.package:
            registers.setdefault(registration.package,
                                 set()).add(f"secret {registration.scheme}://")
    for reporter in self_report.registered_contributors():
        # The self-report seam (ADR-0072): a contributor is visible on the
        # heartbeat only while it has something to say, so this row is the one
        # place a quiet one can be seen to have registered at all.
        if reporter.package:
            registers.setdefault(reporter.package,
                                 set()).add(f"report {reporter.name}")
    # The keeper seam (ADR-0071 §5): at most one, and a working one is silent
    # everywhere else — it says nothing on the heartbeat until it fails, which
    # makes this row the only place an operator can see that the copies are being
    # carried at all, and by which installation.
    if (keeping := registered_keeper()) is not None and keeping.package:
        registers.setdefault(keeping.package, set()).add(f"keeper {keeping.name}")
    return [PackageRow(origin=package_origin(package),
                       registers=tuple(sorted(registers[package])))
            for package in sorted(registers) if package != "little_sister"]


@app.route('/system')
def system() -> ResponseReturnValue:
    user = identity.signed_in()
    if not user.admin:
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
        # package fills which template slot (ADR-0034), which configuration
        # aspects a dependent package added (ADR-0035), and which package answers
        # for each secret scheme (ADR-0064). A seam nobody can see from the
        # running instance is indistinguishable from one that silently did not
        # take.
        #
        # The check-type roster is here for that reason too, and one more: a type
        # may now be registered by a separately released package (ADR-0051), so
        # "which code answers for `type: github`, at which version" is no longer
        # derivable from this repository at all — only from the running process.
        # It is split against the engine's checks (`_type_roster`) so the types
        # this configuration actually runs come first and the rest fold away.
        #
        # The assembled policy is here for the same reason and one more: a source
        # is contributed by a *package*, so a request blocked inside somebody
        # else's code is undebuggable from this instance unless the page says who
        # asked for each origin (ADR-0048 §7).
        in_use, folded = _type_roster(info)
        aspects = [(name, aspect_owner(name)) for name in registered_aspects()]
        body = render_template('system.html', username=user.name,
                               firstname=user.firstname,
                               version=__version__, info=info,
                               rendered_at=rendered_at,
                               instance=this_instance(),
                               instance_named=bool(config.instance),
                               types_in_use=in_use, types_folded=folded,
                               slot_fillers=slots.all_fillers(),
                               packages=_registering_packages(),
                               extra_aspects=aspects,
                               resolvers=registered_resolvers(),
                               doors=identity.registered_doors(),
                               choosing_at_login=identity.choosing_at_login(),
                               system_admin=system_admin.registered(),
                               csp_header=CSP_HEADER,
                               csp_directives=csp_policy.directives)
    response = make_response(body)
    response.headers['X-Rendered-At'] = rendered_at
    return response


@app.route('/copy')
@app.route('/copy/<path:branch>')
def copy(branch: str = "") -> ResponseReturnValue:
    """A hand-off as a **page of its own** — the tree, one node, or one reason.

    One route and three documents, addressed exactly as ADR-0036 decision 12
    settled it for maintenance: the node is a **path**, the entry is a **query
    value** (`?reason=<slug>`), never a path segment — a discovered entry's slug
    contains a `/`, and a percent-encoded one does not survive `PATH_INFO`.

    Why a page rather than a button that copies in place. The per-line control
    lives in the `reason.actions` slot, whose fillers are links; a page keeps it
    one, works with JavaScript off, and — the part that decides it — keeps the
    documents *out of the pages*. The detail page lists every reason uncapped and
    the grid's rail rides the ~10s poll, so a document embedded per line would be
    paid for on every render of the crowded node this feature exists for. Here
    each one is fetched exactly when somebody asks for it.

    The leaf detail page keeps its own inline buttons: that document is one an
    operator standing on the page wants without a navigation, and it is already
    rendered from the snapshot behind that page.
    """
    user = identity.signed_in()
    style = _copy_style()
    # One immutable read for both representations: the rich HTML is rendered from
    # the canonical Markdown below, so a check update can never put two different
    # incidents on the same page (ADR-0002).
    node = status_tree.snapshot(branch) if branch else None
    if branch and node is None:
        return render_template('text.html', username=user.name,
                               firstname=user.firstname,
                               copy_markdown="", copy_html=Markup(""),
                               copy_html_text="", copy_preview=True,
                               copy_subject=branch, copy_missing=True), 404
    if node is not None:
        slug = request.args.get('reason', '')
        line = next((r for r in node.reasons if r.slug == slug), None) if slug else None
        if slug and line is None:
            # A slug this run does not report: **suspended, not deleted**
            # (ADR-0036 decision 6). There is no document to make of a line that
            # is not there, and inventing one from the pin's text would hand over
            # a finding the check is no longer making.
            return render_template('text.html', username=user.name,
                                   firstname=user.firstname,
                                   copy_markdown="", copy_html=Markup(""),
                                   copy_html_text="", copy_preview=True,
                                   copy_subject=node.path,
                                   copy_missing_reason=True), 404
        markdown = (format_reason_markdown(node, line, style) if line is not None
                    else format_node_markdown(node, style, _since_of(branch)))
        subject = node.path
    else:
        markdown = format_copy_markdown(status_tree.snapshot(""), style)
        subject = ""
    rich = render_markdown(markdown) if markdown else Markup("")
    return render_template(
        'text.html', username=user.name,
        firstname=user.firstname, copy_markdown=markdown,
        copy_html=rich, copy_html_text=str(rich), copy_preview=True,
        copy_subject=subject)


def _since_of(branch: str) -> str | None:
    """The start of a node's current own-status period, or ``None`` where it has
    no transition of its own to bound one (ADR-0027) — what the detail page
    computes for the same document, in one place so the two cannot differ."""
    periods = status_tree.history(branch)
    return periods[-1].since if periods else None


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
    user = identity.signed_in()
    links_config = current_links()
    link_probe.refresh_if_due(links_config)
    return render_template('links.html', username=user.name,
                           firstname=user.firstname,
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
    running if there is one (ADR-0030). Whatever has not answered by
    then keeps its previous verdict and age while the pass finishes behind the
    response.

    Open to **every logged-in viewer**, not only an admin: whoever maintains
    `links.yaml` is not necessarily one, and this is the control that person
    needs most. It is the same call the problems block above it already makes.
    """
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


@app.route('/user/avatar')
def user_avatar() -> ResponseReturnValue:
    """Serve only the signed-in user's selected avatar (ADR-0045).

    There is no username or path parameter. Resolution happened at startup from
    a bare name inside the aspect's ``avatars/`` sandbox; the route only looks up
    that result and reads its current bytes. If the file was removed under the
    running process, the packaged neutral avatar is the honest fallback.
    """
    user = identity.signed_in()
    if identity.is_system_admin_session():
        # Never a configured picture, whatever the user list happens to hold under
        # this name: the packaged avatar is how a page says which door you came
        # through, and it is the same answer the context processor gives.
        return redirect(url_for('static', filename='system-admin-avatar.svg'))
    avatar = local_login.registered_avatars().get(user.name)
    if avatar is None:
        return redirect(url_for('static', filename='default-avatar.svg'))
    try:
        payload = read_avatar(avatar)
    except (OSError, ValueError):
        return redirect(url_for('static', filename='default-avatar.svg'))
    response = make_response(payload)
    response.mimetype = avatar.content_type
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
    user = identity.signed_in()
    return render_template('about.html', username=user.name,
                           firstname=user.firstname,
                           version=__version__,
                           rings=watch_lines.rings(),
                           says=watch_lines.says())


@app.route('/favicon.ico')
def favicon() -> ResponseReturnValue:
    return redirect('/static/favicon.ico')


if __name__ == '__main__':
    # use_reloader=False so the engine isn't started twice in dev.
    app.run(debug=True, use_reloader=False)
