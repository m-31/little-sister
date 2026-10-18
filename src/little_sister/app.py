import atexit
import gzip
import json
import math
import os
import re
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import cache, partial
from pathlib import Path
from secrets import token_hex
from typing import Any, Literal
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
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
from markupsafe import Markup, escape

from little_sister import (
    __version__,
    csp,
    first_look,
    identity,
    instants,
    link_probe,
    local_login,
    noise,
    readiness,
    self_report,
    slots,
    system_admin,
    watch_lines,
)
from little_sister.actions import register_builtin_fillers
from little_sister.api import (
    StandingSeries,
    authenticate,
    parse_api_tokens,
    problem,
    series_envelope,
    status_envelope,
)
from little_sister.assets import Assets
from little_sister.checks import Check, CheckError, parse_duration, plain
from little_sister.checks.base import (
    DURATION_UNITS,
    LIBRARY_GRADINGS,
    WINDOW_DECLARATIONS,
    TypeOrigin,
    registered_types,
)
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
    Origin,
    TimeStyle,
    format_node_markdown,
    format_reason_markdown,
    format_tree_markdown,
)
from little_sister.curves import (
    RUNS_LABEL,
    Curve,
    draw,
    draw_runs,
    drawable,
    runs_drawable,
    runs_of,
)
from little_sister.dashboard_layout import (
    CHIP_FACE,
    ChipFace,
    Priced,
    chip_estimate,
    chip_face,
    chip_width,
    dashboard_layout,
)
from little_sister.engine import Engine, EngineInfo, SubjectSeries, create_engine
from little_sister.errors import ConfigError
from little_sister.event_filter import (
    CAUSE_WORDS,
    HELD_WORDS,
    STATUS_WORDS,
    EventFilter,
    FilterRefused,
    read_filter,
)
from little_sister.first_look import Drawn, FirstLooks
from little_sister.grading import MAP, PAIR, SET, SINCE, Graded, Grading
from little_sister.icons import known_names, read_icon
from little_sister.instance import this_instance
from little_sister.keeper import registered_keeper
from little_sister.lease import Lease, LeaseRefused
from little_sister.limits import format_size, format_weight
from little_sister.line_template import Declarations, Declared, Form
from little_sister.links import LINKS_ASPECT, current_links, links_policy_sources
from little_sister.logger import logger, open_log_file
from little_sister.looks import LOOKS, LOOKS_BY_KEY
from little_sister.maintenance import MaintenanceEntry, MaintenanceStore
from little_sister.measures import Measure
from little_sister.nodes import load_nodes, resolve_metadata, run_consistency_pass
from little_sister.origins import PackageOrigin, package_origin
from little_sister.paths import shown_path
from little_sister.reasons import RECORD_TIMESTAMP_KEYS, record_leaves
from little_sister.render import first_block, render_markdown, render_markdown_inline
from little_sister.secrets import (
    SecretError,
    check_reference,
    looks_like_reference,
    registered_resolvers,
    resolve_setting,
)
from little_sister.series import Placed
from little_sister.spans import (
    coarse_span,
    format_duration,
    format_span,
    format_tolerance,
    local_time,
)
from little_sister.state import EVENTS_FILE, SERIES_FILE, StateLayer
from little_sister.status import (
    HEARTBEAT_PATH,
    StatusCode,
    join_path,
    on_same_line,
    split_path,
)
from little_sister.titles import Labeled, shown_title
from little_sister.tree import (
    CAUSE_LINE_PIN_ENDED,
    CAUSE_LINE_PIN_SET,
    CAUSE_PIN_EDITED,
    CAUSE_PIN_ENDED,
    CAUSE_PIN_SET,
    CAUSE_REACHED,
    CAUSE_REMOVED,
    STATE_CODE,
    ChipCounts,
    Event,
    ReasonLine,
    StatusPeriod,
    StatusSnapshot,
    chip_counts,
    events_from_payload,
    failing,
    failing_first,
    healthy,
    last_alive,
    line_healthy,
    nodes_from_payload,
    stale_after_seconds,
    status_tree,
    stopped_at_of,
)
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

# How deep the /status tree renders before stopping, and the ceiling for a
# `depth=` in the address.
MAX_DEPTH = 8
# Remember a viewer's chosen filters (the on/off switches) for a year.
VIEW_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
# The view cookies the band wrote before the wall became a tree (ADR-0127
# decision 7): no longer read, and expired once, on the first answer that finds one.
RETIRED_VIEW_COOKIES = ("depth", "dense")

# Presentation preferences (ADR-0029): how this browser wants the surface to
# look. One cookie holds them, urlencoded so a later key can join without a
# migration, and it is read server-side into body attributes so a page never
# flashes the wrong scheme. Presentation only — nothing here changes what the
# surface *says*, there is no server state, and logging out keeps the look.
PREFS_COOKIE = "ls_prefs"
PREFS_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
# The themes are a look (`looks.py`): their default the deployment's, the library's
# cyberpunk. `default` was the plain theme's name until 2026-10-18; a cookie that
# still says it follows the deployment's default, as any value the roster lacks does.
THEMES = LOOKS_BY_KEY["theme"].values
LAYOUTS = ("rail", "topbar", "kiosk")
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


def _resolve_depth() -> int | None:
    """A ``depth=`` in the address, clamped to ``0..MAX_DEPTH``, or ``None`` where
    the address carries none (or nonsense). The viewer's word for one load, as the
    band's three buttons are (ADR-0127 decision 7): ``depth=N`` closes every node N
    levels below the page's node, the wall's cards being level 1, and ``depth=0``
    closes the page's node itself to one card. Never from or into a cookie."""
    raw = request.args.get("depth")
    if raw is None:
        return None
    try:
        depth = int(raw)
    except ValueError:
        return None
    return max(0, min(depth, MAX_DEPTH))


def _resolve_flag(name: str, default: bool) -> bool:
    """A tri-source on/off view flag: an explicit form
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
    """This browser's layout and each of the looks of `looks.py`, its theme among
    them, read from the one presentation cookie (ADR-0029).

    Every failure mode lands on the defaults, independently per key: no cookie,
    an unparsable one, a key the roster no longer has, a value someone typed by
    hand. A preference is a *look*, so a bad one must never be able to break a
    page — the worst it can do is show the default. A look's default is the
    deployment's (`settings.yaml`), so a browser that never chose one follows it.
    """
    chosen = _chosen_looks()
    values = parse_qs(request.cookies.get(PREFS_COOKIE, ""))
    layout = (values.get("layout") or [""])[0]
    return {
        "layout": layout if layout in LAYOUTS else DEFAULT_LAYOUT,
    } | {look.key: chosen.get(look.key, config.looks[look.key]) for look in LOOKS}


def _chosen_looks() -> dict[str, str]:
    """The looks this browser has chosen, as the presentation cookie keeps them: a
    look the browser never chose is absent, and so is one whose value the look no
    longer has."""
    values = parse_qs(request.cookies.get(PREFS_COOKIE, ""))
    chosen: dict[str, str] = {}
    for look in LOOKS:
        value = (values.get(look.key) or [""])[0]
        if value in look.values:
            chosen[look.key] = value
    return chosen


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
        "layouts": LAYOUTS,
        # The looks a browser chooses and the deployment defaults (`looks.py`), the
        # theme first: the settings menu offers each, and `<body>` carries each one
        # in force.
        "looks": LOOKS,
        "look_values": {look.key: current[look.key] for look in LOOKS},
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


#: Our own stylesheet and scripts, each named by its content (ADR-0112).
own_assets = Assets(Path(app.static_folder or ""))

#: What a hashed URL's answer says: the URL names the content, so a browser may keep
#: it for good. Public, as the files are — the login page links them.
_KEPT_FOR_GOOD = "public, max-age=31536000, immutable"


@app.url_defaults
def _static_by_hash(endpoint: str, values: dict[str, Any]) -> None:
    """Every URL built for one of our stylesheets or scripts carries its hash
    (ADR-0112) — here and not in a template, so no page can link one without."""
    if endpoint != "static" or "v" in values:
        return
    digest = own_assets.digest(str(values.get("filename", "")))
    if digest is not None:
        values["v"] = digest


# What is sent compressed (ADR-0127, on Lex's word of 2026-10-16): the documents and
# the fragments the ten-second refresh fetches, which carry both faces of every node
# and so weigh four to five times what the wall did, and the JSON envelopes, a whole
# tree each — never a static file, which the browser keeps by its hash (ADR-0112) and
# `send_file` streams. The level is gzip's own: on a deployment's recorded wall it
# takes the fragment from 574 KB to 26 KB in 4 ms, beside a render of 100 ms, and a
# further level buys a kilobyte for twice the time. Nothing under a kilobyte is worth
# the header.
GZIP_MIMETYPES = frozenset(
    {"text/html", "application/json", "application/problem+json"})
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 6


@app.after_request
def _compressed_where_asked(response: Response) -> Response:
    """Send a page, a fragment or an envelope gzipped where the request takes gzip.

    Registered first, so it runs last of the application's ``after_request`` hooks:
    the body it compresses is the one every other hook has seen, and the headers they
    set stand. ``Vary: Accept-Encoding`` goes on every answer of these kinds, taken or
    not, so that a cache between here and a browser never hands a compressed answer
    to one that did not ask. Nothing a page carries is a secret to leak by its
    compressed length (the session rides in its cookie, and a pin's compare-and-set
    token is the pin's own time), so the compression-oracle attacks on TLS are no
    reason to send a wall at five times its weight.
    """
    if response.mimetype not in GZIP_MIMETYPES or response.direct_passthrough:
        return response
    response.vary.add("Accept-Encoding")
    if (response.status_code != 200 or "Content-Encoding" in response.headers
            or request.accept_encodings.quality("gzip") <= 0):
        return response
    body = response.get_data()
    if len(body) < GZIP_MIN_BYTES:
        return response
    response.set_data(gzip.compress(body, GZIP_LEVEL, mtime=0))
    response.headers["Content-Encoding"] = "gzip"
    return response


@app.after_request
def _static_kept_for_good(response: Response) -> Response:
    """Say how long the answer to a hashed URL may be kept (ADR-0112).

    The hash the file has now: for good. Another — a page loaded before an upgrade
    asking by the hash it holds — gets the file there is and is told to ask again,
    or a browser would keep the new file under the old name. No hash, or a file
    that has none: as it was.
    """
    asked = request.args.get("v")
    if request.endpoint != "static" or asked is None or response.status_code >= 400:
        return response
    digest = own_assets.digest(str((request.view_args or {}).get("filename", "")))
    if digest is not None:
        response.headers["Cache-Control"] = (
            _KEPT_FOR_GOOD if asked == digest else "no-cache")
    return response


def assets_digest() -> str:
    """One digest of every stylesheet and script a page may link — ours and the
    registered packages' — which a page that refreshes itself states and every part
    it fetches states again (ADR-0112): where they differ, this process links other
    files than the page holds, and the page loads itself afresh."""
    return own_assets.set_digest(asset.digest for asset in slots.assets())


app.jinja_env.globals["assets_digest"] = assets_digest

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

    A view may hand over the assembled policy with what its own page adds
    (``g.csp_page_policy``, :meth:`csp.Policy.adding`) — ``/links`` and the hosts its
    icons load from — and that policy is this response's alone.
    """
    if response.mimetype == "text/html":
        policy = g.get("csp_page_policy", csp_policy)
        response.headers[CSP_HEADER] = policy.header()
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


def _own_address() -> str:
    """The address this page was asked at — its path and its query — as a form on it
    names its way back (``next``, which :func:`_safe_next` reads on the way in).

    Without ``fragment``: the wall's refresh asks for the grid alone by adding it,
    and a pin's editors stand in that grid (ADR-0104 decision 7), so a form the
    refresh drew has to come back to the page and not to the piece of it.
    """
    kept = [(name, value) for name, value in request.args.items(multi=True)
            if name != "fragment"]
    return quote(request.path) + ("?" + urlencode(kept) if kept else "")


@app.template_filter("at_line")
def _at_line(address: str, slug: str) -> str:
    """Where a write to one of a page's lines comes back to: the page as it was asked
    for — a branch's depth and filters kept — at that line, by the address that names
    one (``?reason=<slug>#pinned-reason``, ADR-0036 decision 12), in place of whatever
    line the page was asked at before."""
    parts = urlsplit(address)
    kept = [(name, value)
            for name, value in parse_qsl(parts.query, keep_blank_values=True)
            if name != "reason"]
    return f"{parts.path}?{urlencode([*kept, ('reason', slug)])}#pinned-reason"


def _focus_of(branch: str, node: StatusSnapshot | None
              ) -> tuple[str, MaintenanceEntry | None]:
    """The line a node's page was asked at (``?reason=<slug>``, ADR-0036 decision
    12), and the pin on that slug where the current run did not report the line.

    Such a pin is **suspended, not deleted** (decision 6): the pin is real and the
    line is absent, and the node's own page is the one surface that can say so — a
    fragment could only have failed to scroll, at the moment an operator most needs
    it said. A leaf's page and a branch's ask it alike, since both list their lines.
    """
    if not branch or node is None:
        return "", None
    focus = request.args.get("reason", "")
    if not focus or any(line.slug == focus for line in node.reasons):
        return focus, None
    return focus, status_tree.entry_maintenance(branch, focus)


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
    # A look, the theme among them, is written once the browser has chosen it — in
    # this post, where the menu sends a value the deployment does not default to, or
    # in an earlier one, which the cookie keeps — so a browser that never chose
    # follows the deployment's default when that changes. The menu posts every group
    # at once, each as it stands, so a value equal to the default is no choice by
    # itself. The layout, whose default is a constant, is written as it stands.
    chosen: dict[str, str] = {}
    kept = _chosen_looks()
    for look in LOOKS:
        posted = request.form.get(look.key, "")
        if posted in look.values and (look.key in kept
                                      or posted != config.looks[look.key]):
            chosen[look.key] = posted
        elif look.key in kept:
            chosen[look.key] = kept[look.key]
    layout = request.form.get("layout", "")
    chosen["layout"] = layout if layout in LAYOUTS else current["layout"]
    response = make_response(redirect(_safe_next(request.form.get("next"))))
    response.set_cookie(PREFS_COOKIE, urlencode(chosen),
                        max_age=PREFS_COOKIE_MAX_AGE, samesite="Lax",
                        secure=_connection_is_secure())
    return response


@app.template_filter("status_slug")
def _status_slug(code: StatusCode) -> str:
    """Lower-case status name, used as a CSS class suffix (`s-ok`, `s-error`…)."""
    return code.name.lower()


@app.template_filter("failing_first")
def _failing_first(lines: Iterable[ReasonLine]) -> list[ReasonLine]:
    """A box's lines as its line budget shows them: errors, then warnings, then the
    rest, each group in the check's order (`tree.failing_first`, ADR-0127 decision 6).
    For the clamped block alone; a node's own lines on its page keep the check's
    order."""
    return failing_first(lines)


# --- the wall's tree (ADR-0127): what the templates ask of each node ----------------
#
# One vocabulary over what a node contributes (`tree.py`, backlog #91 §7.9): what the
# healthy fold folds, what a close's incident reads, what a chip counts.

app.jinja_env.globals["healthy"] = healthy
app.jinja_env.globals["failing"] = failing
app.jinja_env.globals["line_healthy"] = line_healthy
app.jinja_env.globals["state_code"] = STATE_CODE.__getitem__
# the cues' shapes, drawn once per page as a sprite (`_status_cue.html`)
app.jinja_env.globals["status_codes"] = tuple(StatusCode)


def _chip_counts_map(node: StatusSnapshot | None) -> dict[str, ChipCounts]:
    """Every node's chip counts by path, taken on the snapshot **before** *hide ok*
    and *hide idle* drop nodes (ADR-0127 decision 2) — as the page's containers are —
    so a filter changes what the page shows and never what a chip says."""
    counts: dict[str, ChipCounts] = {}

    def walk(current: StatusSnapshot) -> None:
        counts[current.path] = chip_counts(current)
        for child in current.children:
            walk(child)

    if node is not None:
        walk(node)
    return counts


def _leaves_map(node: StatusSnapshot | None) -> dict[str, int]:
    """How many leaves stand beneath each branch, by path, on the same unfiltered
    snapshot as the chips' counts: what a branch's chip counts with the tree and
    never with a status, which a level's runs keep room for (`_chip_room`)."""
    leaves: dict[str, int] = {}

    def walk(current: StatusSnapshot) -> int:
        if not current.children:
            return 1
        leaves[current.path] = sum(walk(child) for child in current.children)
        return leaves[current.path]

    if node is not None:
        walk(node)
    return leaves


#: How far past the rest a level's widest name may size its runs' columns: at most
#: this many times the level's 90th-percentile name (backlog #91's note, §2,
#: 2026-10-15), a name past it wrapping inside its column.
CHIP_NAME_BOUND = 1.5


@dataclass(frozen=True)
class ChipRoom:
    """What a level's runs of chips are sized for under the look `chip_runs:
    aligned` (ADR-0127 decision 12): the characters the server counts for their
    column — the widest name's and the largest count's — and the largest count of
    leaves among the level's branches, which `tree.js` keeps room for when it
    measures the names in pixels. The estimate counts each character at the theme's
    letter of a `0` — 0.85 in the system's faces, a whole one in cyberpunk's — and
    adds the chip's chrome, a count's margin among it where the level counts
    (`dashboard_layout.chip_width`, backlog #91's note, §2, 2026-10-17 and
    2026-10-18)."""

    chars: int
    leaves: int

    @property
    def estimate(self) -> str:
        """The column as the stylesheet's length, the level's `--chip-w`, which
        reads the theme's letter."""
        return chip_estimate(self.chars, counts=self.leaves > 0)

    def tenths(self, face: ChipFace) -> int:
        """The same column in the planner's tenths of a pixel, in ``face``."""
        return chip_width(self.chars, counts=self.leaves > 0, face=face)


def _chip_room(children: Sequence[StatusSnapshot],
               leaves: Mapping[str, int]) -> ChipRoom:
    """A level's column width for its runs, from what never changes with status
    (ADR-0127 decision 12): the widest of its children's names, open or closed, at
    most :data:`CHIP_NAME_BOUND` times their 90th percentile, in characters, and the
    digits of the largest count of leaves among its branches — a leaf brings none,
    its total being the count of its lines, which each reading writes. The names
    are the ones the filters leave, as every face the page draws is; the leaves are
    counted on the unfiltered tree, as the chips count them."""
    names = sorted(len(child.name) for child in children)
    if not names:
        return ChipRoom(0, 0)
    typical = names[max(0, math.ceil(0.9 * len(names)) - 1)]
    widest = min(names[-1], math.floor(CHIP_NAME_BOUND * typical))
    most = max((leaves.get(child.path, 0) for child in children if child.children),
               default=0)
    return ChipRoom(widest + (len(str(most)) if most else 0), most)


def _chip_own(child: StatusSnapshot, leaves: Mapping[str, int],
              face: ChipFace) -> int:
    """A closed child's chip at its own width, in the planner's tenths of a pixel, as
    a run that holds one column draws it, wrapping as it comes (backlog #91's note,
    §2, 2026-10-17): its name and the digits of the leaves beneath it where it is a
    branch — a leaf brings none, as its level's estimate has it — with the chrome of
    a chip that draws its count, or none, in ``face``
    (`dashboard_layout.chip_width`)."""
    most = leaves.get(child.path, 0) if child.children else 0
    return chip_width(len(child.name) + (len(str(most)) if most else 0),
                      counts=bool(most), face=face)


#: Every node's first look (ADR-0128), as the start builds it from the loaded
#: checks, the deployment's `nodes.yaml` and `settings.yaml` (`_seed_node_metadata`).
#: Until the start has run, and where no engine runs, `settings.yaml` alone speaks.
first_looks: FirstLooks | None = None


def _first_looks() -> FirstLooks:
    """The resolver the page draws its first look from (`first_look.FirstLooks`)."""
    if first_looks is not None:
        return first_looks
    return FirstLooks((), {}, config, status_tree.named_by_run)


def _first_drawn(node: StatusSnapshot | None, depth_closed: int | None,
                 looks: FirstLooks | None = None, *, dense: bool = True) -> Drawn:
    """What the page draws of ``node``'s nodes as they arrive (`first_look.draw`,
    backlog #91 §7.5): the configured look, today's density where nobody spoke, and
    the failure budget's openings; nothing where the page draws no tree."""
    if node is None:
        return Drawn()
    return first_look.draw(node, looks or _first_looks(), depth_closed=depth_closed,
                           dense=dense)


def _priced(node: StatusSnapshot | None, drawn: Drawn,
            leaves: Mapping[str, int], face: ChipFace = CHIP_FACE) -> Priced:
    """What the planner prices of the page's first look (ADR-0128 decision 6): the
    nodes the configuration closes, each node's line budget, the chips' column width
    of each level a run stands in, the estimate its `--chip-w` carries
    (`_chip_room`), and each of those chips at its own width (`_chip_own`), which a
    run that holds one column wraps by, both in tenths of a pixel in the ``face``
    the browser's theme draws them in — none of it read off a status."""
    chips: dict[str, int] = {}
    own: dict[str, int] = {}

    def walk(current: StatusSnapshot) -> None:
        if any(child.path in drawn.priced for child in current.children):
            chips[current.path] = _chip_room(current.children, leaves).tenths(face)
            for child in current.children:
                if child.path in drawn.priced:
                    own[child.path] = _chip_own(child, leaves, face)
        for child in current.children:
            walk(child)

    if node is not None:
        walk(node)
    return Priced(closed=drawn.priced, caps=drawn.caps, chip_w=chips, chip_own=own)


def _healthy_counts(node: StatusSnapshot) -> tuple[int, int]:
    """What the healthy fold on a node folds (ADR-0127 decision 4): the configured
    fold's count, which leaves a child that claims `show_when_quiet` and a claiming
    node's own quiet lines alone, and a press's, which takes them too (decision 5).
    Both ride on the funnel and on *✓ +N ok*, and `tree.js` draws the one in force."""
    kids = [child for child in node.children if healthy(child)]
    lines = [line for line in node.reasons if line_healthy(node, line)]
    pressed = len(kids) + len(lines)
    configured = (sum(1 for child in kids if not child.show_when_quiet)
                  + (0 if node.show_when_quiet else len(lines)))
    return configured, pressed


app.jinja_env.globals["chip_room"] = _chip_room
app.jinja_env.globals["healthy_counts"] = _healthy_counts


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


#: Where a name wider than its line may break: after an underscore, a dot or a
#: hyphen inside it, so `code_scanning_security` reads `code_scanning_` over
#: `security` rather than `code_scanning_securit` over `y`. The browser breaks at
#: none of the first two by itself, and `overflow-wrap: anywhere` stays the last
#: resort for one word longer than its line.
_NAME_BREAK = re.compile(r"([_.-])(?=.)")


@app.template_filter("breakable")
def _breakable(name: object) -> Markup:
    """``name`` escaped, a `<wbr>` after each `_`, `.` and `-` inside it (backlog
    #91's note, §2, 2026-10-16) — for a name drawn where it may wrap: a card's or
    a box's head, a node page's head and heading, the trail. `<wbr>` is no
    character, so a copied name, a find and the name a screen reader is given are
    the name as it is; an attribute takes the name itself."""
    return Markup(_NAME_BREAK.sub(r"\1<wbr>", str(escape(str(name)))))


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


@app.template_filter("duration")
def _duration(seconds: int | None) -> str:
    """A **configured** interval in the units the config wrote it in — 900 is
    `15m` — as :func:`little_sister.spans.format_duration` writes it.

    A name for the template, not a second implementation; the same relationship
    `elapsed` has to `format_span`. The copy document states a check's frequency
    too, and two implementations of *how this project writes an interval* is
    precisely the drift `spans.py` exists to prevent."""
    return format_duration(seconds)


@app.template_filter("tolerance")
def _tolerance(seconds: float | None) -> str:
    """A freshness tolerance as an interval, as
    :func:`little_sister.spans.format_tolerance` writes it.

    A name for the template, not a second implementation — the relationship
    `duration` has to `format_duration`, and for the same reason: the copy
    document states this number too."""
    return format_tolerance(seconds)


@app.template_filter("elapsed")
def _elapsed(seconds: float | None) -> str:
    """A measured span — a check runtime, a countdown, an uptime — as
    :func:`little_sister.spans.format_span` writes it: ``412 ms``, ``3.1 s``,
    ``43 s``, ``1m 55s``, ``2h 7m``, ``1d 3h``; ``—`` before the first run.

    The filter is a name for the template, not a second implementation: the
    rendering itself is on the public API surface so a check type writing a
    duration into a reason line matches the page it renders onto."""
    return format_span(seconds)


@app.template_filter("weight")
def _weight(size: int) -> str:
    """A weight in bytes — what the series hold, their ceiling — as
    :func:`little_sister.limits.format_weight` writes it: ``812 B``, ``1.6 KiB``,
    ``8.0 MiB``. A name for the template, not a second implementation: the same
    figure stands in the engine's own `series` lines, and the system page names
    it the same way."""
    return format_weight(size)


@app.template_filter("size")
def _size(size: int | None) -> str:
    """A process's size — the resident size, its peak, the memory limit — as
    :func:`little_sister.limits.format_size` writes it: ``312 MiB``, ``8.0 GiB``.
    A name for the template, not a second implementation: the same figures stand
    in the engine's `memory` line and its report, and the system page names them
    the same way (ADR-0095)."""
    return format_size(size)


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


@dataclass(frozen=True)
class _RecordField:
    """One row of a record as its node's page lists it (``_record_list.html``).

    ``kind`` is how the page shows the value, and :func:`_record_fields` is the one
    place that decides it. ``text`` is what the row reads; ``stored`` is the value
    as the record holds it — the same text on a ``plain`` row, and on an
    ``instant`` the UTC string the seam stored, which the page keeps as the
    ``datetime`` of the row's ``<time>``.
    """
    name: str
    kind: Literal["instant", "plain"]
    text: str
    stored: str


@app.template_filter("record_fields")
def _record_fields(value: object) -> list[_RecordField]:
    """A record — a line's, or the one its node measured — flattened into dotted
    names and values for the list the node's own page shows, each with the **kind**
    the page shows it as.

    **The one place a field's kind is decided**: the rest of the typed rendering
    extends this walk rather than adding a second one. The kind is the field's own
    **key**'s, wherever in the record it stands — ``created.at`` is a time as much as
    ``at`` is — and never its value's, and the keys are the seam's:
    :data:`~little_sister.reasons.RECORD_TIMESTAMP_KEYS`, ``at``, ``started`` and
    ``ended``, read here rather than copied, so the page and the seam that enforces
    the vocabulary cannot disagree about it.

    A value under one of those names is an **instant** and reads in the configured
    timezone and ``time_format``, as every other time on the page does (ADR-0006).
    No age stands beside it (ADR-0082 decision 5): a check that grades on an age says
    it in its own sentence. Whatever else stands under a timed name is shown as it
    was stored, like every value under any other name: a null (*this run has not
    ended*), a time the configured zone cannot hold — the seam accepts any instant
    UTC can, and the last half hour of the year 9999 in UTC is the year 10000 in
    Berlin — and a string without an offset, which the seam never lets through and
    the page does not guess at.

    The name is dotted because that is how a record is addressed everywhere else
    (``completed.at``), so what a reader inspects and what they would later write
    are spelled the same — and the names come out of
    :func:`~little_sister.reasons.record_leaves`, the one walk a measure is read
    through as well (ADR-0092), so a field listed here is the field ``measures:``
    names. A list is shown as its JSON rather than exploded into
    ``field[0]``, ``field[1]``, a time inside one included; every other value that
    is not text is shown as its JSON too, so a boolean reads ``true`` and an absent
    value ``null`` instead of in Python's spelling. The values are escaped by the
    template like any other data (ADR-0018) — which is the escaping the check no
    longer has to get right itself.
    """
    rows: list[_RecordField] = []
    for path, key, item in record_leaves(value):
        stored = item if isinstance(item, str) else json.dumps(item)
        shown = _record_instant(item) if key in RECORD_TIMESTAMP_KEYS else None
        rows.append(_RecordField(path, "plain", stored, stored) if shown is None
                    else _RecordField(path, "instant", shown, stored))
    return rows


def _record_instant(value: object) -> str | None:
    """A value under a timed name in the configured zone and format, where it is an
    ISO-8601 string carrying an offset that zone can hold — the form the seam
    stores every time in — and ``None`` for anything the page shows as stored."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    try:
        return _format_local(moment)
    except OverflowError:
        return None


@dataclass(frozen=True)
class _ReadingRow:
    """One kept reading as a row of its node's readings table (ADR-0092 decision 6):
    its place on the series' clock — as the page writes a time, and in UTC for the
    row's ``<time>`` — the code it stood with, the sentence as it stood, and its
    record's fields by name, each as the record list shows it."""
    at: str
    stored: str
    code: StatusCode | None
    texts: tuple[str, ...]
    fields: dict[str, _RecordField]


@dataclass(frozen=True)
class _Column:
    """One column of a readings table and what heads it (ADR-0102 decision 2): the
    field it holds, the label its measure gives it — none where no measure declares
    the field, or where the label is the field's own name — and the measure's unit."""
    field: str
    label: str = ""
    unit: str = ""


@dataclass(frozen=True)
class _Readings:
    """A series' readings as a table shows them (ADR-0097 decision 1): the check
    that keeps it, by its type; the subject they were read of; the node the check
    is mounted on, whose History page has every one; the rows the table lists,
    newest first, with a column for every field they carry — the ones its measures
    declare first, in their order, and then the rest in the record's (ADR-0102
    decision 2); and how many the series keeps in all."""
    title: str
    subject: str
    path: str
    columns: tuple[_Column, ...]
    rows: tuple[_ReadingRow, ...]
    kept: int
    #: How many of them fall in the window the page is drawn over, where it is drawn
    #: over one (ADR-0098 decision 2).
    within: int | None = None


@dataclass(frozen=True)
class _NodeCurves:
    """The curves that stand on one node, as its page shows them (ADR-0097
    decision 2), and where the rest are: the node their series are kept on, and
    this node's group on that node's Series view."""
    curves: tuple[Curve, ...]
    source: str
    anchor: str


@dataclass(frozen=True)
class _CurveGroup:
    """One group of a Series view: the node its curves stand on — by its path below
    the view's own node, for its heading and its anchor, and whole, for its link —
    that node as the tree has it now, where it has it, and the curves."""
    name: str
    path: str
    anchor: str
    node: StatusSnapshot | None
    curves: tuple[Curve, ...]


@dataclass(frozen=True)
class _Quiet:
    """A check at or beneath a Series view's node whose series draw no curve: where
    it is mounted, and how many readings it keeps of how many subjects — and, of
    those, the subjects that have no node of their own, by name, with how many of the
    readings are theirs: a subject whose line shares a node, and one whose node was
    removed (ADR-0109 decision 6), whose kept runs would otherwise read as the
    check's."""
    path: str
    kept: int
    subjects: int
    unstood: tuple[str, ...] = ()
    unstood_kept: int = 0


@dataclass(frozen=True)
class _IndexRow:
    """A node a series is kept on, as the Series index lists it (ADR-0097 decision
    4): the checks keeping it, the curves its own series draw, how many readings
    they hold, when the newest was taken, and where else a reader goes from here
    (ADR-0103 decision 1) — ``curves``, its Series view where a curve stands at or
    beneath it, empty where none does; ``readings``, its History page."""
    path: str
    node: StatusSnapshot | None
    kinds: tuple[str, ...]
    #: The curves its own series draw, each drawn to be seen small beside its label
    #: (ADR-0114 decision 1).
    sparks: tuple[Curve, ...]
    kept: int
    newest: str
    curves: str
    readings: str

    @property
    def labels(self) -> tuple[str, ...]:
        """What each of those curves is called, in their order."""
        return tuple(curve.label for curve in self.sparks)


@dataclass(frozen=True)
class _IndexTop:
    """A root node of the Series index (ADR-0103 decision 3): its own row where it
    keeps a series itself, ``None`` where it keeps nothing; the rows beneath it; and
    its Series view where a curve stands at or beneath it, empty where none does."""
    name: str
    node: StatusSnapshot | None
    own: _IndexRow | None
    rows: tuple[_IndexRow, ...]
    curves: str


def _anchor(relative: str) -> str:
    """A group's id on its Series view: its node's path below the view's own, in the
    characters an id and a URL fragment keep as they are."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", relative).strip("-") or "node"


def _beneath_or_at(path: str, where: str) -> bool:
    return (not where.strip("/") or path == where
            or path.startswith(where.rstrip("/") + "/"))


def _subject_nodes(top: StatusSnapshot | None) -> dict[str, str]:
    """The node that stands for each subject at or beneath ``top`` (ADR-0106 decision
    2): one whose lines name that subject and no other — the first in the tree's
    order, where two do. A line that names no subject names no other."""
    found: dict[str, str] = {}
    stack = [top] if top is not None else []
    while stack:
        node = stack.pop()
        named = {line.subject for line in node.reasons if line.subject}
        if len(named) == 1:
            found.setdefault(named.pop(), join_path(node.path))
        stack.extend(reversed(node.children))
    return found


def _shown(kept: Sequence[SubjectSeries]) -> tuple[dict[int, str], frozenset[int]]:
    """The node each series of ``kept`` is shown on, by the series' ``id``, and the
    ``id`` of each series a node stands for (ADR-0106 decisions 2 and 4): the node at
    or beneath its check's mount that stands for its subject, and its check's own
    node where none does — its line shares a node with another subject's, or it has
    no line now. The object a check declares is its own node's wherever a line names
    it: it is the one reading the engine places, and that node stands for it."""
    nodes: dict[str, dict[str, str]] = {}
    stood: dict[int, str] = {}
    owned: set[int] = set()
    for series in kept:
        mount = join_path(series.check.path)
        if series.subject and series.subject != series.check.subject:
            if mount not in nodes:
                nodes[mount] = _subject_nodes(status_tree.snapshot(mount))
            node = nodes[mount].get(series.subject)
            stood[id(series)] = mount if node is None else node
            if node is not None:
                owned.add(id(series))
        else:
            stood[id(series)] = mount
            owned.add(id(series))
    return stood, frozenset(owned)


def _quiet_of(path: str, found: Sequence[SubjectSeries],
              owned: frozenset[int]) -> _Quiet:
    """What a Series view says of a node none of whose series draws a curve:
    ``found`` are the series shown on it, ``owned`` the ``id`` of each a node stands
    for (:func:`_shown`)."""
    unstood = [series for series in found if id(series) not in owned]
    return _Quiet(path=_url_branch(path),
                  kept=sum(len(one.readings) for one in found),
                  subjects=len(found),
                  unstood=tuple(sorted(series.subject for series in unstood)),
                  unstood_kept=sum(len(one.readings) for one in unstood))


def _stood_on(kept: Sequence[SubjectSeries]) -> dict[int, str]:
    """The node each series of ``kept`` is shown on, by the series' ``id``
    (:func:`_shown`)."""
    return _shown(kept)[0]


def _standing(kept: Sequence[SubjectSeries], *, where: str = "/", on: bool = False,
              stood: Mapping[int, str] | None = None
              ) -> Iterator[tuple[str, Measure, SubjectSeries]]:
    """Every measure ``kept`` declares, expanded over its series' readings, with the
    path of the node its curve would stand on (ADR-0096 decisions 1 and 2): each at
    or beneath ``where`` — or, ``on``, on that node itself — whether or not a reading
    gives it a number. A measure names its node from the node its series is shown
    on, the subject's own where it has one (ADR-0106 decision 2) — ``stood``, where
    the caller has asked already."""
    stood = _stood_on(kept) if stood is None else stood
    for series in kept:
        records = [placed.record.data for placed in series.readings]
        for declared in series.check.measures.values():
            for measure in declared.expand(records):
                path = join_path(stood[id(series)], measure.node)
                if (path == join_path(where) if on
                        else _beneath_or_at(path, where)):
                    yield path, measure, series


def _plots(kept: Sequence[SubjectSeries], *, where: str = "/", on: bool = False
           ) -> Iterator[tuple[str, Measure | None, SubjectSeries,
                               list[Placed] | None]]:
    """Everything ``kept`` draws at or beneath ``where`` — or, ``on``, on that node
    itself — with the path of the node it stands on, none of it drawn yet.

    A **curve** for each declared measure a reading gives a number (ADR-0096
    decision 4). And for a series **of runs** — one that keeps a record with an
    identity — its runs as marks (ADR-0111), handed back beside the measure: as
    stems under each measure a run gives a number; and, where none of its measures
    draws, as ticks under no measure at all, on the node that stands for its
    subject. Where no node does, it draws no ticks — its readings are listed on its
    check's History page (ADR-0109 decision 6) — so a type that has not moved its
    lines shows what it showed (ADR-0106)."""
    stood, owned = _shown(kept)
    here = join_path(where)
    runs = {id(series): runs_of(series.readings) for series in kept}
    measured: set[int] = set()
    for path, measure, series in _standing(kept, stood=stood):
        its_runs = runs[id(series)]
        if its_runs:
            if not runs_drawable(measure, its_runs):
                continue
            measured.add(id(series))
        elif not drawable(measure, series.readings):
            continue
        if path == here if on else _beneath_or_at(path, where):
            yield path, measure, series, its_runs or None
    for series in kept:
        its_runs = runs[id(series)]
        path = stood[id(series)]
        if (its_runs and id(series) in owned and id(series) not in measured
                and (path == here if on else _beneath_or_at(path, where))):
            yield path, None, series, its_runs


def _drawable(kept: Sequence[SubjectSeries], *, where: str = "/"
              ) -> dict[str, list[tuple[str, SubjectSeries]]]:
    """What :func:`_drawn` draws at or beneath ``where``, drawing none of it: by the
    path of the node each curve stands on, its label and the series it is drawn
    from, in the order :func:`_drawn` has them (ADR-0096 decision 4) — for a page
    that lists curves or asks which series have one."""
    found: dict[str, list[tuple[str, SubjectSeries]]] = {}
    for path, measure, series, _runs in _plots(kept, where=where):
        found.setdefault(path, []).append(
            (RUNS_LABEL if measure is None else measure.label, series))
    return found


def _now() -> datetime:
    """The server's clock, as a page reads it: what a window's ``now`` is
    (ADR-0098 decision 1)."""
    return instants.now()


def _times() -> Callable[[datetime], str]:
    """How a page writes an instant — :func:`little_sister.spans.local_time`, in the
    configured zone and format — remembering what it wrote for as long as the page
    is rendered, and no longer: a curve writes the time of every reading it is drawn
    over, the curves of one series are drawn over the same readings, and formatting
    an instant costs more on macOS than the rest of a curve does."""
    return cache(local_time)


def _drawn(kept: Sequence[SubjectSeries], *, where: str = "/", on: bool = False,
           span: tuple[datetime, datetime] | None = None,
           times: Callable[[datetime], str] | None = None,
           within: tuple[datetime, datetime] | None = None,
           small: bool = False
           ) -> dict[str, list[tuple[Curve, SubjectSeries]]]:
    """Every curve ``kept`` draws at or beneath ``where`` — or, ``on``, on that node
    itself — by the path of the node it stands on (ADR-0096 decisions 1, 2 and 4):
    each declared measure expanded over its series' readings, drawn against the
    tolerance its own check's period implies and on ``span`` where a page shares one
    time axis, every instant written by ``times``, the page's :func:`_times` — one of
    its own where none is handed. One with no number to draw is left out before it
    is drawn — over everything kept, so that drawn over ``within``, the window a
    Series view is drawn over, a curve with no reading there keeps its place and
    says so (ADR-0098 decision 2). A series of runs is drawn as its marks
    (:func:`_plots`, ADR-0111). ``small`` draws each to be seen small, writing no
    instant (ADR-0114 decision 1)."""
    times = _no_time if small else times or _times()
    drawn: dict[str, list[tuple[Curve, SubjectSeries]]] = {}
    windowed: dict[int, Sequence[Placed]] = {}
    for path, measure, series, runs in _plots(kept, where=where, on=on):
        if runs is not None:
            inside = windowed.setdefault(id(series), _inside(runs, within))
            curve = draw_runs(measure, inside, span=span, times=times)
        else:
            assert measure is not None
            readings = windowed.setdefault(id(series),
                                           _inside(series.readings, within))
            # The check's period, not its node's tolerance: the two agree where the
            # check alone writes the node — no check states a tolerance of its own —
            # and a node two checks share carries the period of whichever wrote last.
            tolerance = stale_after_seconds(series.check.frequency_seconds)
            curve = draw(measure, readings, tolerance=tolerance, span=span,
                         times=times, small=small)
        drawn.setdefault(path, []).append((curve, series))
    return drawn


def _readings(series: SubjectSeries, *, every: bool = False,
              times: Callable[[datetime], str] | None = None,
              within: tuple[datetime, datetime] | None = None,
              shown_on: str | None = None) -> _Readings:
    """A series' newest readings as a table — as many as ``reading_cap`` says, the
    check's own where it states one and ``settings.yaml``'s otherwise — or,
    ``every``, all of them; each row's time written by ``times``, the page's
    :func:`_times` where its curves have written it already. ``within`` is the
    window a Series view is drawn over, whose newest readings the table holds
    (ADR-0098 decision 2). ``shown_on`` is the node the series is shown on, whose
    History page has every one — the check's own where none is handed."""
    cap = (series.check.reading_cap if series.check.reading_cap is not None
           else config.reading_cap)
    inside = _inside(series.readings, within)
    newest = inside[::-1]
    rows = tuple(_reading_row(reading, times)
                 for reading in (newest if every else newest[:cap]))
    return _Readings(
        title=series.check.type_name, subject=series.subject,
        path=_url_branch(shown_on or series.check.path),
        columns=_columns(series, rows),
        rows=rows, kept=len(series.readings),
        within=len(inside) if within is not None else None)


def _columns(series: SubjectSeries, rows: Sequence[_ReadingRow]
             ) -> tuple[_Column, ...]:
    """The columns of a series' readings table (ADR-0102 decision 2): a field its
    measures declare, expanded over the series' records as its curves are, headed by
    the measure's label and unit, and first, in the order declared; then every other
    field the rows carry, by its name, in the record's order — read from the oldest
    record on, so a field the newest reading happens to lack keeps its place, and a
    table of the newest few orders its columns as the table of all of them does.
    Only fields some row carries stand: a declaration names no column of its own."""
    carried = {name for row in rows for name in row.fields}
    records = [placed.record.data for placed in series.readings]
    present = dict.fromkeys(name for record in records
                            for name, _key, _value in record_leaves(record)
                            if name in carried)
    declared: dict[str, _Column] = {}
    for measure in series.check.measures.values():
        for expanded in measure.expand(records):
            if expanded.field in present and expanded.field not in declared:
                declared[expanded.field] = _Column(
                    expanded.field,
                    "" if expanded.label == expanded.field else expanded.label,
                    expanded.unit)
    return (*declared.values(),
            *(_Column(name) for name in present if name not in declared))


def _inside(readings: Sequence[Placed], within: tuple[datetime, datetime] | None
            ) -> Sequence[Placed]:
    """The readings a window holds, ends included — all of them without one."""
    if within is None:
        return readings
    start, end = within
    return [reading for reading in readings if start <= reading.at <= end]


def _node_curves(node: StatusSnapshot | None) -> _NodeCurves | None:
    """The curves that stand on ``node`` — an aspect's own, or a check's own node's
    for a measure that names no other (ADR-0097 decision 2) — and none where no
    engine runs."""
    if engine is None or node is None:
        return None
    kept = engine.series_near(node.path)
    here = _drawn(kept, where=node.path, on=True).get(join_path(node.path), [])
    if not here:
        return None
    # The node its series is shown on: the check's own — or the subject's, whose
    # History page has that subject's readings (ADR-0106 decision 4).
    source = _stood_on(kept)[id(here[0][1])]
    return _NodeCurves(curves=tuple(curve for curve, _series in here),
                       source=_url_branch(source),
                       anchor=_anchor(_beneath(join_path(node.path), source)))


def _beneath(path: str, above: str) -> str:
    """``path`` below ``above``, which it is at or beneath: empty for the node."""
    return path[len(above.rstrip("/")):].strip("/")


def _history_readings(node: StatusSnapshot | None) -> tuple[_Readings, ...]:
    """Every reading of each series shown on ``node``, for its History page, beneath
    its status periods (ADR-0106 decision 4): the series of the subject the node
    stands for; and, on a check's own node, what the check keeps of its own object
    and of every subject no node stands for — both checks of a shared mount."""
    if engine is None or node is None:
        return ()
    here = join_path(node.path)
    kept = engine.series_near(node.path)
    stood = _stood_on(kept)
    return tuple(_readings(series, every=True, shown_on=here)
                 for series in kept if stood[id(series)] == here)


def _no_time(at: datetime) -> str:
    """An instant a drawing does not say: what a sparkline's curve is drawn with."""
    return ""


def _series_count(branch: str) -> int:
    """How many curves the Series view of the node at ``branch`` draws (ADR-0114
    decision 3): the ones that stand at or beneath it — every one the instance has
    for the root, whose Series tab is the index. Counted and not drawn."""
    if engine is None:
        return 0
    where = join_path(branch)
    return sum(len(standing) for standing
               in _drawable(engine.series_near(where), where=where).values())


def _series_tab(branch: str) -> bool:
    """Whether the Series tab stands on the node at ``branch``: a curve can stand at
    or beneath it, as the configuration says (ADR-0097 decision 3) — or a series is
    shown at or beneath it on a subject's own node, or a curve of that series stands
    there, which only the tree says: it knows where a grading wrote the subject's
    line (ADR-0106 decision 4). Read from the lines and the measures declared, never
    from a reading's numbers, so the tab still does not come and go with them."""
    if engine is None:
        return False
    if engine.curves_may_stand(branch):
        return True
    where = join_path(branch)
    kept = engine.series_near(where)
    return (any(_beneath_or_at(shown, where) for shown in _stood_on(kept).values())
            or any(True for _ in _standing(kept, where=where)))


@dataclass(frozen=True)
class _Window:
    """The window a Series view is drawn over (ADR-0098 decision 1): its two ends —
    ``None`` where the URL leaves one to what is kept — the parameters as they were
    written, which the page's Series crumbs carry on, and the one reading of the
    clock the page takes, which its ``now`` is and its controls measure against."""

    start: datetime | None
    end: datetime | None
    written: Mapping[str, str]
    now: datetime


class _WindowRefused(ValueError):
    """A window parameter the server cannot read: answered ``400``, naming it."""

    def __init__(self, name: str, said: Markup) -> None:
        super().__init__(name)
        self.name = name
        self.said = said


#: What a window's end may be written as, for a refusal to say.
_WINDOW_FORMS = Markup("<code>now</code>, <code>now-6h</code> or an instant such as "
                       "<code>2026-09-30T14:00</code>")

#: The presets a Series view offers (ADR-0098 decision 3): the words, and the
#: duration back from now in the family's units — a year is 365 days until the units
#: say so.
_PRESETS = (("1h", "1h"), ("6h", "6h"), ("12h", "12h"), ("1d", "1d"), ("1w", "1w"),
            ("30d", "30d"), ("1y", "365d"), ("7y", "2555d"))

#: The family's units a window back from now is written in, the largest first.
_AGO_UNITS = (("w", 7 * 86400), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1))

#: How the bar says a window's length, the largest first: a year is 365 days, as
#: the presets write one.
_LENGTH_WORDS = ((365 * 86400, "year"), (7 * 86400, "week"), (86400, "day"),
                 (3600, "hour"), (60, "minute"), (1, "second"))


def _window(args: Mapping[str, str]) -> _Window:
    """The window a request's ``from`` and ``to`` name (ADR-0098 decision 1): each
    ``now``, ``now-`` and a duration, or an instant — one without an offset read in
    the configured timezone; ``to`` now where it is left out, and no window without
    either. What cannot be read raises :class:`_WindowRefused`."""
    written = {name: args[name] for name in ("from", "to") if args.get(name)}
    now = _now()
    start = _instant("from", written["from"], now) if "from" in written else None
    end = (_instant("to", written["to"], now) if "to" in written
           else now if start is not None else None)
    if start is not None and end is not None and start >= end:
        raise _WindowRefused("from", Markup(
            "The window's <code>from</code> has to come before its <code>to</code>."))
    return _Window(start, end, written, now)


def _instant(name: str, text: str, now: datetime) -> datetime:
    """One end of a window, in UTC."""
    from little_sister.config import config as settings
    written = text.strip()
    if written == "now":
        return now
    if written.startswith("now-"):
        try:
            seconds = parse_duration(written[4:], 0)
        except CheckError:
            seconds = 0
        if seconds > 0:
            return now - timedelta(seconds=seconds)
    else:
        try:
            moment = datetime.fromisoformat(written)
        except ValueError:
            pass
        else:
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=settings.tzinfo)
            return moment.astimezone(UTC)
    raise _WindowRefused(name, Markup(
        "The window's <code>{}</code> cannot be read as {}: write {}.").format(
            name, text, _WINDOW_FORMS))


def _written_window(start: datetime, end: datetime) -> dict[str, str]:
    """A window as the page writes it into a link: two instants in UTC."""
    return {"from": _utc_instant(start), "to": _utc_instant(end)}


def _series_url(branch: str, window: Mapping[str, str] | None = None,
                anchor: str = "") -> str:
    """The Series view of the node at ``branch``, over ``window`` as written, at the
    group ``anchor`` names where one does."""
    values: dict[str, Any] = dict(window or {})
    return url_for("series", path=branch, _anchor=anchor or None, **values)


def _ago(length: timedelta) -> dict[str, str]:
    """A window of ``length`` that ends now, as a link writes it (ADR-0098 decision
    3): ``now-`` and the length to the minute — to the second under one — in the
    largest of the family's units that holds it whole."""
    seconds = max(1, round(length.total_seconds()))
    if seconds >= 60:
        seconds = round(seconds / 60) * 60
    unit, size = next((unit, size) for unit, size in _AGO_UNITS if seconds % size == 0)
    return {"from": f"now-{seconds // size}{unit}"}


def _back_from_now(window: _Window) -> int | None:
    """The length, in seconds, of a window written back from now — ``now-`` and a
    duration, to now — and ``None`` for any other."""
    start = window.written.get("from", "").strip()
    if not start.startswith("now-") or window.written.get("to", "now").strip() != "now":
        return None
    return parse_duration(start[4:], 0)


def _length_words(seconds: int) -> str:
    """A length as the bar says it: a whole number of the largest unit that holds
    it — *1 hour*, *30 days*, *7 years*."""
    size, word = next((size, word) for size, word in _LENGTH_WORDS
                      if seconds % size == 0)
    count = seconds // size
    return f"{count} {word}" + ("" if count == 1 else "s")


def _utc_instant(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class _WindowLink:
    """One control of a window's bar: its words, where it leads — nowhere where it
    does not apply, which the bar shows disabled — whether it is the window the page
    is drawn over, and its ``rel``."""

    words: str
    href: str = ""
    current: bool = False
    rel: str = ""


@dataclass(frozen=True)
class _WindowEnd:
    """One end of the window as its bar names it: to the minute in the configured
    zone, the instant itself for ``<time datetime>``, and the zone's name where the
    bar writes it after this end."""

    text: str
    stored: str
    zone: str


@dataclass(frozen=True)
class _WindowBar:
    """The bar above a Series view's curves and the Events page's log (ADR-0098
    decision 3, ADR-0101 decision 4): the window named — in words where it has any,
    and by its ends — its presets, and its four moves."""

    name: str
    ends: tuple[_WindowEnd, ...]
    presets: tuple[_WindowLink, ...]
    moves: tuple[_WindowLink, ...]


def _zone() -> str:
    """The configured timezone's name, as a page hands it to a script."""
    from little_sister.config import config as settings
    return settings.timezone


def _window_ends(start: datetime, end: datetime) -> tuple[_WindowEnd, ...]:
    """The window's ends as its bar names them: to the minute in the configured
    zone, the end without its date on the start's day, and the zone's name once,
    after the end — after each where the clock changed between them; a window of
    one instant is named by it alone."""
    from little_sister.config import config as settings
    first, last = start.astimezone(settings.tzinfo), end.astimezone(settings.tzinfo)
    full = "%Y-%m-%d %H:%M"
    if start == end:
        return (_WindowEnd(first.strftime(full), _utc_instant(start),
                           first.tzname() or ""),)
    changed = first.tzname() != last.tzname()
    return (_WindowEnd(first.strftime(full), _utc_instant(start),
                       (first.tzname() or "") if changed else ""),
            _WindowEnd(last.strftime("%H:%M" if last.date() == first.date() else full),
                       _utc_instant(end), last.tzname() or ""))


def _window_bar(url: Callable[[Mapping[str, str]], str], window: _Window,
                span: tuple[datetime, datetime],
                kept: tuple[datetime, datetime]) -> _WindowBar:
    """The bar that names the window a page is drawn over and moves it (ADR-0098
    decision 3) — a node's Series view, or the Events page (ADR-0101 decision 4) —
    measured against the one reading of the clock the page took and against the
    oldest and newest of what the page keeps. ``url`` writes where a window leads,
    keeping whatever else the page's URL says. The presets run up to the first that
    reaches back past the oldest thing kept, the one of the window's length marked
    where the window is written back from now. The four moves keep their places:
    *earlier* and *later* by half the window's length, *zoom out* doubling it around
    its middle, *now* ending it now with its length kept — each leading nowhere where
    it does not apply. A window a move leaves ending now or after is written back from
    now; any other as two instants."""
    now = window.now
    oldest, newest = kept
    start, end = span
    live = _back_from_now(window)
    presets: list[_WindowLink] = []
    for words, duration in _PRESETS:
        seconds = parse_duration(duration, 0)
        presets.append(_WindowLink(
            words, url({"from": f"now-{duration}"}), current=live == seconds))
        if seconds >= (now - oldest).total_seconds():
            break
    presets.append(_WindowLink("all kept", url({}), current=not window.written))

    def written(moved_start: datetime, moved_end: datetime) -> str:
        return url(_ago(moved_end - moved_start) if moved_end >= now
                   else _written_window(moved_start, moved_end))

    named = bool(window.written)
    half = (end - start) / 2
    moves = (
        _WindowLink("← earlier", written(start - half, end - half), rel="prev")
        if named and start > oldest else _WindowLink("← earlier"),
        _WindowLink("zoom out", written(start - half, end + half))
        if named and not (start <= oldest and end >= newest)
        else _WindowLink("zoom out"),
        _WindowLink("later →", written(start + half, end + half), rel="next")
        if named and end < now else _WindowLink("later →"),
        _WindowLink("now", url(_ago(end - start)))
        if named and end < now else _WindowLink("now"))
    name = ("Everything kept" if not named
            else f"Last {_length_words(live)}" if live is not None else "")
    return _WindowBar(name=name, ends=_window_ends(start, end),
                      presets=tuple(presets), moves=moves)


def _tree_order(top: StatusSnapshot | None) -> list[str]:
    """The path of every node at or beneath ``top``, in the tree's own order: a
    node before its children, and siblings as the snapshot has them — by rank and
    then by name (ADR-0055)."""
    order: list[str] = []
    stack = [top] if top is not None else []
    while stack:
        snapshot = stack.pop()
        order.append(join_path(snapshot.path))
        stack.extend(reversed(snapshot.children))
    return order


def _series_view(branch: str, window: _Window | None = None
                 ) -> dict[str, object] | None:
    """What the Series view of the node at ``branch`` shows (ADR-0097 decision 1),
    or ``None`` where nothing may stand there: every curve at or beneath the node
    on one time axis, grouped by the node each stands on in the tree's order; the
    newest readings of each series they were drawn from; and each check beneath
    whose series draw no curve."""
    if not _series_tab(branch) or engine is None:
        return None
    where = join_path(branch)
    kept = engine.series_near(where)
    stood, owned = _shown(kept)
    # The axis spans the series the curves are drawn from, not every series near:
    # a check above that draws nothing here does not stretch it.
    drawing = {id(series) for standing in _drawable(kept, where=where).values()
               for _label, series in standing}
    drawers = [series for series in kept if id(series) in drawing]
    moments = [placed.at for series in drawers for placed in series.readings]
    kept_span = (min(moments), max(moments)) if moments else None
    # The window the URL names, its open ends filled from what is kept (ADR-0098
    # decisions 1 and 2): the axis is the window as written, not trimmed to it.
    window = window or _Window(None, None, {}, _now())
    span = ((window.start or kept_span[0], window.end or kept_span[1])
            if kept_span is not None else None)
    # One writing of each instant for the whole view: its curves, its range and its
    # tables of readings are over the same readings.
    times = _times()
    drawn = _drawn(drawers, where=where, span=span, times=times, within=span)
    tree_order = _tree_order(status_tree.snapshot(branch))
    order = [path for path in tree_order if path in drawn]
    order += sorted(path for path in drawn if path not in tree_order)
    groups = tuple(
        _CurveGroup(name=_beneath(path, where) or _url_branch(path),
                    path=_url_branch(path), anchor=_anchor(_beneath(path, where)),
                    node=status_tree.snapshot(path),
                    curves=tuple(curve for curve, _series in drawn[path]))
        for path in order)
    readings = tuple(_readings(series, times=times,
                               within=span if window.written else None,
                               shown_on=stood[id(series)])
                     for series in drawers)
    # A node none of whose series draws anything is named with what it keeps: a
    # check's own, and a subject's (ADR-0106 decision 4).
    drew = {id(series) for curves in drawn.values() for _curve, series in curves}
    showing: dict[str, list[SubjectSeries]] = {}
    for series in kept:
        if _beneath_or_at(stood[id(series)], where):
            showing.setdefault(stood[id(series)], []).append(series)
    quiet = {path: found for path, found in showing.items()
             if not any(id(series) in drew for series in found)}
    return {
        "groups": groups, "readings": readings,
        "quiet": tuple(_quiet_of(path, quiet[path], owned) for path in sorted(quiet)),
        "first": times(span[0]) if span else "",
        "last": times(span[1]) if span else "",
        # what the view's script reads (ADR-0098 decision 6): the window's two
        # instants, and the zone its times are written in
        "start": _utc_instant(span[0]) if span else "",
        "end": _utc_instant(span[1]) if span else "",
        "zone": _zone(),
        "bar": (_window_bar(partial(_series_url, branch), window, span, kept_span)
                if span is not None and kept_span is not None else None),
        "zoom": lambda start, end, anchor="": _series_url(
            branch, _written_window(start, end), anchor),
        "times": times}


def _series_standing(top: StatusSnapshot, window: _Window
                     ) -> tuple[StandingSeries, ...]:
    """Every series the series read answers at the node ``top`` (ADR-0106 decision
    6, ADR-0122 decision 3), over ``window``.

    A series is here where the node it is shown on (:func:`_shown`) is ``top`` or
    beneath it, and, shown above it, where one of its measures names a node at or
    beneath it. Which series stand is read from where the lines stand and from what
    is declared (:func:`_standing`), never from a reading's numbers, and from
    everything kept: one with no reading inside the window keeps its place and
    answers none. Each carries the measures that stand at or beneath ``top`` — one
    for every key its kept readings hold, with the path of the node its curve stands
    on (decision 4) — and its readings whose time on the series' clock the window
    holds, both ends included, an end the URL left open bounding nothing.

    In order (decision 6): a node above ``top`` first, the shallowest before the
    deeper; then the tree's own order at and beneath it; and by type, mount and
    subject where several stand on one node. None where no engine runs.
    """
    if engine is None:
        return ()
    where = join_path(top.path)
    kept = engine.series_near(where)
    stood = _stood_on(kept)
    measures: dict[int, list[tuple[Measure, str]]] = {}
    for path, measure, series in _standing(kept, where=where, stood=stood):
        measures.setdefault(id(series), []).append((measure, path))
    beneath = {path: place for place, path in enumerate(_tree_order(top))}

    def place(series: SubjectSeries) -> tuple[int, int, str, str, str, str]:
        node = stood[id(series)]
        if node in beneath:
            rank = (1, beneath[node])
        elif _beneath_or_at(where, node):
            rank = (0, node.count("/"))
        else:
            # at or beneath by its path, and no node of the tree: a mount its
            # check has not written since the start
            rank = (2, 0)
        return (*rank, node, series.check.type_name, join_path(series.check.path),
                series.subject)

    found = sorted((series for series in kept
                    if _beneath_or_at(stood[id(series)], where)
                    or id(series) in measures), key=place)
    return tuple(StandingSeries(
        node=stood[id(series)], type_name=series.check.type_name,
        mount=join_path(series.check.path), subject=series.subject,
        measures=tuple(measures.get(id(series), ())),
        readings=tuple(placed for placed in series.readings
                       if (window.start is None or window.start <= placed.at)
                       and (window.end is None or placed.at <= window.end)))
        for series in found)


def _series_index() -> tuple[_IndexTop, ...]:
    """Every node a series is kept on, grouped under its root node (ADR-0097
    decision 4)."""
    if engine is None:
        return ()
    kept = engine.series_near("/")
    # A row for every node a series is shown on (ADR-0106 decision 4): a check's own
    # node, and each node that stands for one of its subjects.
    stood = _stood_on(kept)
    by_mount: dict[str, list[SubjectSeries]] = {}
    for series in kept:
        by_mount.setdefault(stood[id(series)], []).append(series)
    # Which curves each node has, each drawn to be seen small (ADR-0114 decision
    # 1) — and with no instant written: a curve costs a formatted time for every
    # reading it is drawn over, and a sparkline says none of them.
    sparks: dict[str, list[Curve]] = {}
    for standing in _drawn(kept, small=True).values():
        for curve, series in standing:
            sparks.setdefault(stood[id(series)], []).append(curve)
    # A node's Series view is offered where a curve stands at or beneath it: its
    # own series draw one, or a mount beneath it does (ADR-0103 decision 1).
    drawing = [_url_branch(mount) for mount in by_mount if sparks.get(mount)]

    def curves_at_or_beneath(path: str) -> str:
        beneath = any(drawn == path or drawn.startswith(path + "/")
                      for drawn in drawing)
        return url_for("series", path=path) if beneath else ""

    tops: dict[str, list[_IndexRow]] = {}
    for mount in sorted(by_mount):
        found = by_mount[mount]
        newest = max(placed.at for series in found for placed in series.readings)
        path = _url_branch(mount)
        tops.setdefault(path.split("/", 1)[0], []).append(_IndexRow(
            path=path, node=status_tree.snapshot(mount),
            kinds=tuple(dict.fromkeys(series.check.type_name for series in found)),
            sparks=tuple(sparks.get(mount, ())),
            kept=sum(len(series.readings) for series in found),
            newest=local_time(newest, "%Y-%m-%d %H:%M"),
            curves=curves_at_or_beneath(path),
            readings=url_for("history", path=path)))
    # A root appears once: where it keeps a series itself, its own row is its
    # heading (ADR-0103 decision 3).
    return tuple(_IndexTop(name=name, node=status_tree.snapshot(name),
                           own=next((row for row in rows if row.path == name), None),
                           rows=tuple(row for row in rows if row.path != name),
                           curves=curves_at_or_beneath(name))
                 for name, rows in tops.items())


def _reading_row(reading: Placed,
                 times: Callable[[datetime], str] | None = None) -> _ReadingRow:
    """One reading as its table row: the fields through :func:`_record_fields`, the
    one place a field's kind is decided, so a time in it reads in the configured
    zone and everything else as it was stored; the reading's own time written by
    ``times`` where the page hands one."""
    return _ReadingRow(
        at=(times or _format_local)(reading.at),
        stored=instants.stamp(reading.at),
        code=reading.record.code, texts=reading.record.texts,
        fields={field.name: field for field in _record_fields(reading.record.data)})


def _copy_style() -> TimeStyle:
    """The clock a copy document is written with: this deployment's zone and
    format, resolved once per document so one hand-off cannot straddle a reload."""
    return TimeStyle(config.tzinfo, config.time_format)


@app.template_filter("localtime")
def _localtime(value: datetime | None, fmt: str | None = None) -> str:
    """Render an instant in the configured timezone (config/settings.yaml),
    optionally with an explicit strftime ``fmt`` (the timezone always stays
    the configured one) — and an em dash where there is none.
    """
    if not value:
        return "—"
    return _format_local(value, fmt)


def _filter_snapshot(node: StatusSnapshot,
                     hidden: set[StatusCode]) -> StatusSnapshot | None:
    """Drop nodes (and their subtrees) whose effective code is in `hidden`."""
    if node.code in hidden:
        return None
    kept = tuple(
        f for f in (_filter_snapshot(child, hidden) for child in node.children)
        if f is not None)
    return replace(node, children=kept)


def _nothing_left(hidden: Sequence[StatusSnapshot], under: str = "") -> str:
    """What a wall says when hide ok and hide idle leave none of the nodes it shows:
    what they hid, in the switches' own words — *All 14 nodes are ok.*, *The only
    node is idle.*, *11 nodes are ok and 3 are idle.* — so that an empty page on a
    good day reads as all well, never as nothing reporting.

    ``hidden`` is every node the filters dropped, and each is OK or UNDEFINED, the
    two codes they drop. ``under`` names the node a branch's page is about, whose
    own state stands in its head above the sentence. Empty where nothing was
    hidden: an empty tree says instead that no check reports."""
    if not hidden:
        return ""
    ok = sum(1 for node in hidden if node.code is StatusCode.OK)
    idle = len(hidden) - ok
    where = f" beneath {under}" if under else ""
    if not ok or not idle:
        word = "ok" if ok else "idle"
        if len(hidden) == 1:
            return f"The only node{where} is {word}."
        return f"All {len(hidden):,} nodes{where} are {word}."
    return (f"{ok:,} {'node' if ok == 1 else 'nodes'}{where} "
            f"{'is' if ok == 1 else 'are'} ok and "
            f"{idle:,} {'is' if idle == 1 else 'are'} idle.")


def _node_meta_map(node: StatusSnapshot | None) -> dict[str, dict[str, str | int]]:
    """Path → what the inspection card (ADR-0019) says of a node's ``about``, for
    every node of ``node``'s subtree that has one: its first block, rendered
    (``about``), and how many blocks follow it (``more``), which the card counts as
    *… 3 more paragraphs on its page*.

    The card's heading is the node's name and title as its own head draws them,
    which every node's box carries, open or closed, so the map carries neither: a
    title that only repeats the name is already dropped there (`titles.py`), and a
    node with neither a title nor an ``about`` has no card. The map rides in every
    fragment of the refresh (`_status_grid.html`), so a node a run names after the
    load has its card and a changed ``about`` is current. (``description`` is not
    in the card: it stays on the node's own page, beneath its head's row.)"""
    out: dict[str, dict[str, str | int]] = {}
    if node is None:
        return out
    stack = [node]
    while stack:
        current = stack.pop()
        if current.about:
            block, more = first_block(current.about)
            if block:
                out[current.path] = {"about": str(block), "more": more}
        stack.extend(current.children)
    return out


@dataclass(frozen=True)
class _MaintenancePin:
    """**One pin** — a node's, or one of its reasons' (ADR-0014, ADR-0036). What the
    uncapped ``/maintenance`` page states as one block, which has room for a whole
    pin (ADR-0104 decision 6), and what the popover's rows are folded from.

    **Two texts, and they must never be taken for each other.** ``line`` is *what* is
    silenced — the reason line an entry pin covers, empty on a node pin, which covers
    the node whole — and ``note`` is *why*, the admin's justification. Both are
    called "reason" in the model (``ReasonLine.text`` and ``MaintenanceEntry.reason``)
    and they are not the same kind of thing at all; a page that shows one in the
    other's place is the confusion this naming exists to prevent. The **slug never
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

    Who is behind a pin reads differently by surface (ADR-0014): the popover has
    room for one name and takes ``set_by`` — the writer whose note it is showing —
    while the ``/maintenance`` page has room for the whole sentence, *pinned by Anna
    three days ago, last changed by Ben an hour ago*, and reads it from ``entry``.
    That is the stored pin itself, which the page hands to the block that states it
    and holds its editor — the token it edits against included. ``None`` only on a
    pin built by hand.

    ``suspended`` says that **no node stands at the pin's path** (ADR-0109 decision
    4): its check no longer reports the node, or has not written it yet in this
    process. The pin is held all the same, silences nothing, and holds again when
    the node returns. Such a pin has no title and no line to show — both went with
    the node — and only the Maintenance page lists it: the wall counts what is
    silenced now.
    """
    path: str
    title: str
    note: str
    remaining: str
    expires_at: datetime
    slug: str = ""
    line: str = ""
    #: Where this pin sits **among the pins of its own node** — the index of the
    #: reason line it covers, and ``-1`` for the node's own pin so that one sorts
    #: first. Deliberately *not* called `order`: since ADR-0055 that word means a
    #: node's declared rank among its **siblings**, and this object is `Labeled`,
    #: so the two would sit one attribute apart with different meanings.
    slot: int = -1
    total: int = 0
    set_by: str = ""
    entry: MaintenanceEntry | None = None
    suspended: bool = False

    @property
    def name(self) -> str:
        """The pinned node's own name — the last segment of its path. The page
        heads a node's pins with the whole path, whose tail *is* the name, so a title
        repeating it duplicates there exactly as it does on a chip; this is what lets
        the `node_title` filter ask the question here too (`titles.py`)."""
        return self.path.rsplit("/", 1)[-1]


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


@app.template_filter("time_left")
def _time_left(value: datetime | None) -> str:
    """What is left of a pin, as its block says it beside the instant (ADR-0104
    decision 1): ``1d 23h left``, or ``expired`` once past — the maintenance
    index's reading of the same stored expiry (:func:`_pin_view`), the time from
    the clock's instant to the pin's."""
    if not value:
        return "expired"
    remaining = _humanize_remaining((value - _now()).total_seconds())
    return remaining if remaining == "expired" else f"{remaining} left"


@app.template_filter("expiry_input")
def _expiry_input(value: datetime | None) -> str:
    """A stored expiry as the maintenance form's field reads one: the date and
    the time to the second, in the configured timezone (ADR-0104 decision 5).

    An edit fills its expiry field with this and carries it once more as
    ``expiry_was``. A field that still says it keeps the stored instant, so the
    text is shown and compared and never read back — which is why a second is
    fine enough for it, and why the hour a clock change repeats may be written
    here although the field could not take it typed. Empty where there is no
    expiry, which leaves the field a new pin's.

    The zone is read where :func:`_maintenance_expiry` reads it, so what the
    field shows and how the field is read cannot come apart.
    """
    if not value:
        return ""
    return value.astimezone(config.tzinfo).strftime("%Y-%m-%d %H:%M:%S")


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
    elapsed = int((_now() - value).total_seconds())
    if elapsed < 60:
        return f"at {_format_local(value, '%H:%M')}"
    return f"> {coarse_span(elapsed)} ago"


def _pin_remaining(entry: MaintenanceEntry, now: datetime) -> str:
    """How long a pin has left at ``now``, as an index row words it."""
    return _humanize_remaining((entry.expires_at - now).total_seconds())


def _pin_view(node: StatusSnapshot, entry: MaintenanceEntry, now: datetime, *,
              slug: str = "", line: str = "", slot: int = -1) -> _MaintenancePin:
    """One stored pin as an index row. ``slug`` / ``line`` / ``slot`` are set for an
    **entry** pin and left at their defaults for a node's own."""
    return _MaintenancePin(
        path=node.path, title=node.title, note=entry.reason,
        remaining=_pin_remaining(entry, now), slug=slug, line=line, slot=slot,
        total=len(node.reasons), expires_at=entry.expires_at,
        set_by=entry.set_by, entry=entry)


def _suspended_pins(whole: StatusSnapshot | None,
                    now: datetime) -> list[_MaintenancePin]:
    """The pins **no node stands for** (ADR-0109 decision 4), for the Maintenance
    page: every pin the tree holds against a path that ``whole`` — the snapshot the
    page lists the others from — holds no node at. Read against that one snapshot,
    so a node that leaves or returns while the page is built puts its pins in one
    list or the other, and never in both or in neither.

    A node's own pin first, then its lines' **in the order they were pinned**: the
    check's order went with the lines, and a slug is opaque."""
    reported: set[str] = set()
    stack = [whole] if whole is not None else []
    while stack:
        node = stack.pop()
        reported.add(node.path)
        stack.extend(node.children)
    nodes, lines = status_tree.pins()
    pins = [
        _MaintenancePin(
            path=path, title="", note=entry.reason,
            remaining=_pin_remaining(entry, now), expires_at=entry.expires_at,
            set_by=entry.set_by, entry=entry, suspended=True)
        for path, entry in nodes.items() if path not in reported]
    held = sorted(((path, slug, entry) for (path, slug), entry in lines.items()
                   if path not in reported),
                  key=lambda pin: (pin[0], pin[2].created_at, pin[1]))
    for slot, (path, slug, entry) in enumerate(held):
        pins.append(_MaintenancePin(
            path=path, title="", note=entry.reason,
            remaining=_pin_remaining(entry, now), slug=slug, slot=slot,
            expires_at=entry.expires_at, set_by=entry.set_by, entry=entry,
            suspended=True))
    return pins


@dataclass(frozen=True)
class _NoNode:
    """What is known of a path **no node stands at** (ADR-0116), for the page that
    answers its address: read from the event log and the pins, which keep it
    already — nothing is stored for the page.

    ``path`` is the path as an address writes it and ``pin_path`` as the tree does.
    ``removed`` is when the node left, as the page prints a time, and ``reason`` the
    sentence its removal was logged with — both empty where the last event the log
    holds at the path is not a removal. ``events`` opens the Events page on the path
    and what was beneath it, and is empty where the log holds nothing there.
    ``above`` is the nearest path above that a node stands at — empty where that is
    the root — ``above_series`` whether that node has a Series view, and
    ``first_level`` whether the path is one segment long, so that the root is its
    parent and not merely what is left. ``pins`` are the ones held against the path
    or beneath it (:func:`_suspended_pins`), in that function's order: by path, a
    node's own first."""

    path: str
    pin_path: str
    removed: str
    reason: str
    events: str
    above: str
    above_series: bool
    first_level: bool
    pins: list[_MaintenancePin]


def _no_node(branch: str, now: datetime) -> _NoNode:
    """What the log and the pins know of ``branch``, a path the tree holds no node
    at. The removal is the **last** event at the path itself: a node that left and
    was never written again ends on it, and one a path beneath a removed node names
    has no event of its own, the removal being logged per node that stood."""
    held = join_path(branch)
    path = _url_branch(held)
    recorded = [event for event in status_tree.recent_events()
                if event.path == held or event.path.startswith(held + "/")]
    own = [event for event in recorded if event.path == held]
    removed = reason = ""
    if own and own[-1].cause == CAUSE_REMOVED:
        removed = _format_local(own[-1].timestamp)
        reason = " ".join(own[-1].reason)
    names = [name for name in path.split("/") if name]
    above = ""
    for depth in range(len(names) - 1, 0, -1):
        candidate = "/".join(names[:depth])
        if status_tree.snapshot(candidate) is not None:
            above = candidate
            break
    return _NoNode(
        path=path, pin_path=held, removed=removed, reason=reason,
        events=url_for('events', under=held) if recorded else "",
        above=above, above_series=bool(above) and _series_tab(above),
        first_level=len(names) == 1,
        pins=[pin for pin in _suspended_pins(status_tree.snapshot(""), now)
              if pin.path == held or pin.path.startswith(held + "/")])


def _no_node_page(user: identity.Identity, branch: str) -> ResponseReturnValue:
    """The answer to an address no node stands at (ADR-0116 decision 1): one page
    for every view of a node, and a ``404`` — the address names nothing, and a
    client that follows links learns so from the status."""
    return render_template(
        'no_node.html', username=user.name, firstname=user.firstname, node=None,
        branch=branch, no_node=_no_node(branch, _now()),
        is_admin=user.admin,
        maintenance_default=config.maintenance_default_expiry,
        maintenance_timezone=config.timezone), 404


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


def _pins_above(branch: str) -> list[tuple[str, MaintenanceEntry]]:
    """The pins set on the nodes above ``branch``, outermost first, each with the
    path it stands on.

    A node's pin silences everything beneath it (ADR-0041), so the page of a node
    beneath one is silenced by it as much as by a pin of its own — and is the one
    page that would otherwise not say so. It states each as the pin's block, where
    it acts, without buttons, since a pin is edited where it stands (ADR-0104
    decision 2). A pin on one of a node's **lines** silences that line
    alone (ADR-0124), so only a node's own pin is one of these. Read from the
    tree's table rather than from a snapshot of every node above: the path's
    ancestors are all the nodes there are to ask, and the root is one of them.
    """
    segments = split_path(branch)
    above: list[tuple[str, MaintenanceEntry]] = []
    for depth in range(len(segments)):
        path = join_path(*segments[:depth])
        entry = status_tree.maintenance_entry(path)
        if entry is not None:
            above.append((path, entry))
    return above


def _maintenance_pins(node_pins: list[_MaintenancePin],
                      entry_pins: list[_MaintenancePin],
                      suspended: Sequence[_MaintenancePin] = ()
                      ) -> list[_MaintenancePin]:
    """Every pin in one list for ``/maintenance``: by path, a node's own pin first,
    then its entries in the check's order — and among them the ``suspended`` ones,
    which no node stands for (:func:`_suspended_pins`)."""
    return sorted([*node_pins, *entry_pins, *suspended],
                  key=lambda pin: (pin.path, pin.slot))


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
        # The soonest to clear leads the row, by the instant it ends at.
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
# itself be a secret reference (`scheme://address`, ADR-0023), which the server's
# start resolves (ADR-0091) —
# otherwise a random per-start key: secure by default, at the price of sessions
# resetting on restart (one worker, ADR-0001, so no cross-worker key skew). A
# malformed reference (unknown scheme) fails the import loudly; an
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


def _at_start(name: str) -> bool:
    """Whether the setting ``name`` is a reference, which the server's start resolves
    rather than the import (ADR-0091 decision 8): a reference reaches a store, and an
    import is not an instance. A malformed one is refused here, since saying so
    reaches nothing."""
    value = os.environ.get(name, "")
    if not looks_like_reference(value):
        return False
    check_reference(value)
    return True


#: Whether ``SECRET_KEY`` waits for the start. Until then a random key stands in, and
#: an application nobody starts keeps it — its banner says why.
_SECRET_KEY_AT_START = _at_start("SECRET_KEY")
app.secret_key = token_hex(32) if _SECRET_KEY_AT_START else _session_key()


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

# The same moment a third time, asked about the log (ADR-0121 decision 4). Every
# package has declared the noise caps of the dependencies it brings, and the code of
# the slot has set the levels it sets — so each cap can be judged against all of it,
# and is set only where that takes lines away and nobody chose a level: not the
# deployment's code, and not `LOG_LEVEL` by name, whose named entries are said here a
# second time so that they stand over that code. Nothing is set where a cap is
# declared, which is what keeps the order of a deployment's imports from deciding
# what its log holds. Setting a level writes nothing an instance keeps, so an import
# may do it (ADR-0091); the lines this logs, one for each cap that was set, are where
# a log that leaves lines out says which. A cap that was not set leaves none out and
# has no line: `/system/installed` says why it was not.
noise.settle()

# API tokens for the JSON backend (ADR-0008): "name=token,name2=token2" — set
# directly, or as a value that is itself a secret reference (ADR-0023), which the
# server's start resolves (ADR-0091).
# Unresolvable ⇒ no tokens (the API rejects all requests until restart)
# rather than a crash-loop; a malformed reference still fails the import loudly.
def _api_token_setting() -> str:
    try:
        return resolve_setting(os.environ.get("LITTLE_SISTER_API_TOKENS", ""))
    except SecretError as error:
        self_report.startup.note(
            "api-tokens",
            plain(f"the LITTLE_SISTER_API_TOKENS reference did not resolve "
                  f"({error}); the JSON API rejects every request until a restart"))
        return ""


_API_TOKENS_AT_START = _at_start("LITTLE_SISTER_API_TOKENS")
api_tokens: dict[str, str] = ({} if _API_TOKENS_AT_START
                              else parse_api_tokens(_api_token_setting()))


#: The engine's error until the server's start has run (ADR-0091 decision 5): what an
#: imported application says on every page until something starts it — and all a
#: gunicorn line without the hooks module ever says. The flag is the whole fix.
NOT_STARTED = ("this server imported the application and never started it: gunicorn "
               "starts it with --config python:little_sister.gunicorn_hooks on its "
               "command line, and the development server is "
               "python -m little_sister.app")

# The monitoring engine, which the server's start builds and starts (ADR-0091) —
# once, in the process that serves, and never at the import. Disable it with
# LITTLE_SISTER_ENGINE=0. A bad check *config* is non-fatal — the web app still
# serves behind the banner below; an unusable configuration *tree* is not caught
# at all and stops the start (ConfigError, ADR-0031).
engine: Engine | None = None
# Why there is no engine: :data:`NOT_STARTED` until the start has run, then the
# ``CheckError`` reason when the checks config failed to load; ``None`` with an
# engine and where a server was started with ``LITTLE_SISTER_ENGINE=0``. Feeds the
# header banner so a config typo doesn't take monitoring down with only a log line
# to show for it; persists until a restart with fixed config.
engine_error: str | None = NOT_STARTED
#: The state layer this process runs on (ADR-0071), kept here so an action on a
#: ``/little-sister`` child can be followed by a flush (ADR-0076 decision 6);
#: ``None`` where no engine runs, which is also every test that does not set one.
state_layer: StateLayer | None = None
#: The state directory's lease (ADR-0090), once the start has taken it: the readiness
#: node asks it whether this instance still saves, and the stop lets it go.
lease: Lease | None = None
_start_lock = threading.Lock()
_started = False
_stopped = False


def _engine_switched_off() -> bool:
    return os.environ.get("LITTLE_SISTER_ENGINE", "1").lower() in ("0", "false", "no")


def _resolve_settings() -> None:
    """The start's half of the two settings that may be references (ADR-0091
    decision 8): resolved here, where an instance begins."""
    global api_tokens
    if _SECRET_KEY_AT_START:
        app.secret_key = _session_key()
    if _API_TOKENS_AT_START:
        api_tokens = parse_api_tokens(_api_token_setting())


def start() -> None:
    """The server's start (ADR-0091): what makes this imported application an
    instance — once, in the process that serves, and never at the import.

    gunicorn reaches it through :mod:`little_sister.gunicorn_hooks`'s
    ``post_worker_init``, right after the worker's import and before it serves; the
    development server from ``__main__``, before ``app.run``. In order: the state
    directory's lease (ADR-0090), first, so that a process it refuses has touched
    nothing in the directory, its log file included; the log file, which begins with
    what the import logged; the settings that are references; then the engine, built
    from the checks' configuration, restored and started — with ``atexit`` as the
    backstop of :func:`stop`. A server started with ``LITTLE_SISTER_ENGINE=0`` takes
    no lease and builds no engine. A second call does nothing.

    :raises LeaseRefused: another process holds the state directory. Logged first,
        naming the holder, to stderr: the log file there is the holder's. Under
        gunicorn it is the worker's boot error, which halts the server.
    """
    global _started, engine_error
    with _start_lock:
        if _started:
            return
        _started = True
        if _engine_switched_off():
            open_log_file()
            _resolve_settings()
            engine_error = None
            logger.info("engine disabled via LITTLE_SISTER_ENGINE")
        else:
            state = StateLayer(interval_seconds=config.state_interval)
            held = Lease(state.directory, mark=this_instance().mark)
            try:
                how = held.take()
            except LeaseRefused as refused:
                logger.error("start: %s — this process restores, runs and saves "
                             "nothing, and does not serve", refused)
                raise
            try:
                _start_engine(state, held, how)
            except BaseException:
                held.release()
                raise
        atexit.register(stop, trigger="atexit")


#: How the start came by the lease (ADR-0090), in words that cannot be read as the
#: lease's own state: a lease taken from a released one is held.
_TAKEN = {"free": "a free directory", "released": "a lease its holder released",
          "gone": "a holder that is gone", "lapsed": "a holder whose lease had lapsed"}


def _start_engine(state: StateLayer, held: Lease, how: str) -> None:
    """The start once the lease is this process's: the log, the settings, and the
    engine — built, restored and started."""
    global engine, engine_error, state_layer, lease
    lease = held
    state.hold(held)
    open_log_file()
    logger.info("state: took the lease on %s, from %s", state.directory,
                _TAKEN.get(how, how))
    _resolve_settings()
    state_layer = state
    try:
        built = create_engine(state=state)
    except CheckError as error:
        engine_error = str(error)
        # Log only, on purpose: with no engine there is no tick to read a
        # self-report line on, and the dashboard's stale beat is the report.
        logger.warning("engine not started: %s", error)
        return
    engine_error = None
    _restore_state(built, state)
    _restore_series(built, state)
    _seed_node_metadata(built)
    engine = built
    built.start()


def stop(*, trigger: str = "a call") -> None:
    """The instance's stop (ADR-0088): the links probe's pass abandoned, then the
    engine's stop — the runs in flight abandoned, one save, the lease let go — or,
    where the start built no engine, the lease let go. gunicorn reaches it through
    :mod:`little_sister.gunicorn_hooks`'s ``worker_exit``, with ``atexit`` as the
    backstop, and ``trigger`` says which in the engine's one line. A second call
    does nothing, and says nothing."""
    global _stopped
    with _start_lock:
        if _stopped:
            return
        _stopped = True
    link_probe.stop_probing()
    if engine is not None:
        engine.stop(trigger=trigger)
    elif lease is not None:
        lease.release()


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
    word: the first is a server started with ``LITTLE_SISTER_ENGINE=0`` and getting
    exactly what it asked for, the second is a configuration this instance could not
    load — or a server that never started the engine at all, whose gunicorn line is
    missing the hooks module (ADR-0091). Reporting them the same would make a
    deliberate quiet indistinguishable from a broken one, which is the confusion this
    whole application exists to remove.
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
    fatal — node metadata must not stop monitoring. The file as loaded is kept by
    the engine for the life of the process (ADR-0128): what a path's `children:`
    says is read as each child is written, since no path names the children. And
    the page's first look is built from it, the checks and `settings.yaml` — the
    checks' alone where the file was not read."""
    global first_looks
    try:
        declared = load_nodes()
        metadata = resolve_metadata(engine.checks, declared)
    except CheckError as error:
        self_report.startup.note(
            "nodes",
            plain(f"nodes.yaml was not loaded ({error}); every node shows what its "
                  f"check says and none of the metadata written there"))
        first_looks = FirstLooks(engine.checks, {}, config, status_tree.named_by_run)
        return
    engine.declare_nodes(declared)
    first_looks = FirstLooks(engine.checks, declared, config, status_tree.named_by_run)
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


#: The reason the instance's own node gives for the gap a restart leaves in its
#: history (ADR-0094 decision 4).
NOT_RUNNING = "the instance was not running"


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
    kept file so this process writes it on the tick. With the log comes its table of
    what every node last showed and what its check last reported, which a node's
    first reading is compared with and its wait counts from, row or no row
    (ADR-0110); what it says of a node no configured check covers is forgotten, once
    the pins are replayed. A restart is no transition of a
    subject's (ADR-0094), and the instance's own node records the gap: its restored
    period closes when the old process was last alive — the later of the stamp its
    stop's one save wrote into the log and the lease's last beat before this process
    took it — so ``/little-sister``'s history reads the time nothing watched. Then
    maintenance: attach the store, replay non-expired pins — whose transitions append
    to the restored log, as this process's first events, where the log does not hold
    the pin already (ADR-0094) — and reap any whose path neither a configured check
    nor the instance's own node covers (ADR-0014). The layer itself is the first
    self-report contributor: a
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
            # Read whole before anything is taken (ADR-0120): one time without a
            # zone — an event's, a node's, the stop's — refuses the file.
            events, shown = events_from_payload(payload), nodes_from_payload(payload)
            stopped_at = stopped_at_of(payload)
            restored = status_tree.restore_events(events, shown)
        except ValueError as error:
            state.report_load_failure(EVENTS_FILE, str(error))
        else:
            logger.info("state: restored %d event(s) from %s", restored,
                        state.path(EVENTS_FILE))
            since = last_alive(stopped_at,
                               lease.previous_beat if lease is not None else None)
            if since is not None and status_tree.close_unobserved(
                    HEARTBEAT_PATH, since, NOT_RUNNING):
                logger.info("state: %s was not running from %s until this start",
                            HEARTBEAT_PATH, local_time(since))
    state.keep(EVENTS_FILE, status_tree.events_payload,
               restore=status_tree.adopt_events)
    store = MaintenanceStore(state, tree=status_tree)
    status_tree.use_maintenance_store(store)
    nodes, entry_pins = store.load_all()
    status_tree.restore_maintenance(nodes, entry_pins=entry_pins)
    # What is covered: the line of every configured check, and the instance's own.
    # Its node and its children are no check's, and a pin on one of them — which
    # ADR-0071 decision 4 and ADR-0076 decision 1 count on — is no orphan.
    covered = [*engine.check_roots(), HEARTBEAT_PATH]
    reaped = status_tree.reap_uncovered(covered)
    if reaped:
        logger.info("maintenance: reaped %d orphaned pin(s): %s",
                    len(reaped), ", ".join(sorted(reaped)))
    forgotten = status_tree.forget_uncovered(covered)
    if forgotten:
        logger.info("state: forgot what %d node(s) last showed, which no configured "
                    "check covers: %s", len(forgotten), ", ".join(forgotten))
    self_report.register_contributor(
        "state", state.lines, title="State", report=state.report,
        about="What a restart keeps — the maintenance pins, the event log and the "
              "series under `var/state/` — and whether it was restored, written and, "
              "where a "
              "keeper is registered, carried off the machine (ADR-0071); and what "
              "a takeover set aside as `.bak`, which *take the backups* swaps back "
              "(ADR-0077).")
    self_report.register_action("state", "take-backups", "Take the backups",
                                state.take_backups)


def _restore_series(engine: Engine, state: StateLayer) -> None:
    """Put back the series the last process kept, and keep writing them
    (ADR-0087) — once, post-fork, before the engine runs.

    After :func:`_restore_state`, which has already fetched what a keeper holds, so
    an instance on a fresh machine comes up with the series the old one wrote. The
    file is read whole or not at all: one of another shape is a load failure, a
    line on the ``state`` child for the life of the process, and the series start
    empty. What it holds is put back as it was written; this configuration's
    retention meets it on the engine's first tick, whose sweep drops a series no
    configured check keeps and holds the rest to their counts and the ceiling.

    Registered as a kept file with the store's own ``restore`` as its other
    direction, so a keeper's takeover adopts the store's copy (ADR-0077) and a
    backup swapped back replaces the series the same way.
    """
    payload = state.read(SERIES_FILE)
    if payload is not None:
        try:
            engine.series.restore(payload)
        except ValueError as error:
            state.report_load_failure(SERIES_FILE, str(error))
        else:
            logger.info("state: restored %d series from %s",
                        sum(used.series for used in engine.series.usage().values()),
                        state.path(SERIES_FILE))
    state.keep(SERIES_FILE, engine.series.payload, restore=engine.series.restore)


#: The machine's trust store, measured **once** here and never again (ADR-0073).
#: It is the one thing in the readiness answer that touches the machine, and a
#: report on the seam is recorded state rather than a probe (ADR-0072), so the
#: measurement happens at startup and everything afterwards reads this.
trust_store = readiness.measure_trust_store()


def _first_pass_done() -> bool:
    """Whether there is a first pass to wait for and the engine has finished it.

    The two ways to have no engine are not one answer (ADR-0066 §2 draws the same
    line for ``/health``). A server started with ``LITTLE_SISTER_ENGINE=0`` has
    **no pass to wait for** and is ready at once — a deliberate quiet is not a
    thing to keep traffic away from. A configuration this instance could not load
    leaves an engine that will never run one, and so does a server that never
    started it (ADR-0091); that instance never becomes ready: it serves, its banner
    explains itself to whoever opens it, and a balancer with a working instance
    beside this one sends traffic there.
    """
    if engine is not None:
        return engine.outcomes.first_pass
    return engine_error is None


def _check_outcomes() -> readiness.Outcomes | None:
    """What the engine's checks last stored, or ``None`` where no engine runs —
    an instance with no engine makes no claim about checks it is not running."""
    return engine.outcomes if engine is not None else None


#: This instance's readiness (ADR-0073), and the contributor that carries its
#: lines to ``/little-sister``. Registered here rather than in the
#: import-before-app block, and asked each time: two of the three conditions are
#: only settled once that block has run and the server's start has started the
#: engine, and the lease the start takes is what says whether this instance still
#: saves (ADR-0090).
instance_readiness = readiness.Readiness(
    doors=lambda: bool(identity.registered_doors()),
    trust=lambda: trust_store,
    first_pass=_first_pass_done,
    outcomes=_check_outcomes,
    lost=lambda: lease.lost if lease is not None else None)
self_report.register_contributor(
    "readiness", instance_readiness.lines, title="Readiness",
    about="Whether this instance can be sent traffic — what `/ready` answers, and "
          "the two silent failures of a first rollout as lines (ADR-0073) — and "
          "whether it still saves what it observes (ADR-0090).")
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


def _wants_json() -> bool:
    """Whether this request asks for a resource's JSON: one URL, and `Accept`
    chooses the representation (ADR-0080 decision 8). A browser, and a request that
    says nothing, get the page."""
    return request.accept_mimetypes.best_match(
        ("text/html", "application/json")) == "application/json"


def _series_json(branch: str) -> Response:
    """The series read (ADR-0106 decision 6, ADR-0122): every series that stands at
    or beneath the node at ``branch`` — the root's, ``""``, every series the instance
    keeps — over the window the URL names, behind the bearer token, in one response.

    A node that stands answers a list, empty where no series stands at or beneath
    it. Three things are refused, in the page's order: a request without a valid
    token, a path no node stands at, and a window the server cannot read — the last
    with the page's own sentence, its markup taken off (ADR-0122 decision 7).
    """
    if authenticate(request.headers.get("Authorization"), api_tokens) is None:
        return _api_problem(401, "Unauthorized",
                            "A valid bearer token is required.")
    node = status_tree.snapshot(branch)
    if node is None:
        return _api_problem(404, "Not Found",
                            f"No status node at path {branch!r}.")
    try:
        window = _window(request.args)
    except _WindowRefused as refused:
        return _api_problem(400, "Bad Request", refused.said.striptags())
    return _api_json(series_envelope(
        join_path(branch), _series_standing(node, window), start=window.start,
        end=window.end, version=__version__, engine=_engine_state(),
        now=window.now))


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


def _containers(node: StatusSnapshot | None) -> frozenset[str]:
    """Which of the nodes a page draws hold others: the viewed node and every node
    beneath it with children — a card, a nested box, or its card at depth 0.

    Read before a filter drops a child. A pin on a node covers everything beneath it
    whether or not the page shows it, and the editor an admin's ‖ opens in a node's
    box says what its pin would cover (ADR-0104 decision 3, ADR-0127 decision 3) —
    so a node *hide ok* left without children still says *and everything beneath
    it*, which its ‖ carries as ``data-beneath``.
    """
    if node is None:
        return frozenset()

    def beneath(drawn: StatusSnapshot) -> Iterator[str]:
        if drawn.children:
            yield drawn.path
            for child in drawn.children:
                yield from beneath(child)

    return frozenset(beneath(node))


@app.route('/status')
@app.route('/status/<path:branch>')
def status(branch: str = "") -> ResponseReturnValue:
    # JSON backend mode (ADR-0080): content-negotiated, token-gated, read-only.
    if _wants_json():
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
    # A path no node stands at has a page of its own (ADR-0116). The part an open
    # page's refresh asks for is answered below as any other, and says the same: the
    # page was a node's when it loaded, and its script takes a 200.
    if node is None and branch and not request.args.get('fragment'):
        return _no_node_page(user, branch)
    # A leaf node (a check) gets its own detail page — on a load. The part an open
    # page's refresh asks for is a fragment whatever the node has become: a branch's
    # page polls on after a run named none of its children, and is answered with
    # the grid for a node without any, not with a leaf's page, which the page's
    # script would read as a lost session (ADR-0127 decision 10). The next load of
    # the address is the leaf's page.
    if branch and node is not None and not node.children \
            and not request.args.get('fragment'):
        # The current period's start — or None when this node has no transition of its
        # own to bound one, in which case the page reports the single observation
        # instead of a from/until of one instant (ADR-0027).
        since = _since_of(branch, node)
        # `?reason=<slug>` names one line of this node — the addressing shape
        # ADR-0036 decision 12 settled on, never a path segment. The maintenance
        # index links here with it, and a line's write from this page comes back
        # with it, because on a node with 150 findings "the right page" is not the
        # same as "the line", and the page marks the one it names.
        focus, focus_orphan = _focus_of(branch, node)
        return render_template('check.html', username=user.name,
                               firstname=user.firstname, node=node,
                               # Its fold as its files say (ADR-0128): ✓ ok is a
                               # leaf page's one fold, and it starts as configured.
                               drawn=_first_drawn(node, None),
                               # The curves that stand on this node (ADR-0097
                               # decision 2), and the views beside this one.
                               node_curves=_node_curves(node), view="status",
                               series_tab=_series_tab(branch),
                               series_count=_series_count(branch),
                               # Which checks are reached **through** this one: the
                               # other end of a shield, and the only place the cost
                               # of one is visible before it is paid.
                               dependents=status_tree.dependents(branch),
                               branch=branch, since=since,
                               # A leaf shows what it counts for itself, so
                               # nothing beneath it makes it so: this is None.
                               made_by=_made_by(node), focus=focus,
                               focus_orphan=focus_orphan,
                               pins_above=_pins_above(branch),
                               is_admin=user.admin,
                               maintenance_default=config.maintenance_default_expiry,
                               maintenance_timezone=config.timezone)
    # A branch page renders the same node-facts block as the leaf page (ADR-0044
    # decision 8), so it needs the same `since`: the start of the node's current
    # **own**-status period, from its own transition log — a container has one of
    # those like any other node, which is half of why the block can be shared.
    # None on the overview root, which is nobody's node. Taken from the node before
    # any filter below removes its children, which the rule is about.
    since = _since_of(branch, node) if branch and node else None
    # And the node beneath it that makes what it shows, which the card's first line
    # names with that node's own period (ADR-0123 decision 3) — from the same
    # unfiltered node, since a filter that hides a child cannot change what made it.
    made_by = _made_by(node) if branch and node else None
    # A branch's page lists the node's own lines as a leaf's does, so it is asked at
    # one of them the same way — the index's link and a line's write come back with
    # `?reason=<slug>` — and says the same of a pin whose line is absent.
    focus, focus_orphan = _focus_of(branch, node)
    # The pins above the node, which silence it as much as one of its own: its
    # head states them, and the refresh's fragment renders the head again.
    pins_above = _pins_above(branch) if branch and node else []
    # The same curves as the leaf page's, from the unfiltered node: the curves that
    # stand on it (ADR-0097 decision 2), which the poll renders again.
    node_curves = _node_curves(node) if branch else None
    # Lift the engine self-heartbeat into the status strip (ADR-0024) before filtering,
    # so it shows there always — never as a card, never hidden by hide-ok.
    node, heartbeat = _split_heartbeat(node)
    # What a pin's editor on this page says and where its write comes back to
    # (ADR-0104 decisions 3 and 7): which cards hold other nodes, read before a
    # filter below drops a child, and the page's own address, with its filters and
    # its depth — the same from the page and from the refresh's fragment.
    containers = _containers(node)
    here = _own_address()
    hide_ok = _resolve_flag('hide_ok', False)
    hide_idle = _resolve_flag('hide_idle', False)
    # Surface the maintenance set (ADR-0014) from the *unfiltered* snapshot, so the
    # index and the "contains maintenance" pips survive hide-idle and any depth.
    now = _now()
    node_pins, entry_pins, maintenance_ancestors = _maintenance_view(node, now)
    maintenance_rows = _maintenance_rows(node_pins, entry_pins)
    # What each chip counts (ADR-0127 decision 2), from the same unfiltered
    # snapshot: a filter changes what the page shows, never what a chip says.
    chip_counts_by_path = _chip_counts_map(node)
    # and how many leaves each branch has, which its level's runs keep room for
    chip_leaves = _leaves_map(node)
    # What the grid says where the filters leave none of the nodes it shows: what
    # they hid. With hide ok on, the wall is the list of problems and empty on a good
    # day, and it must read as all well there rather than as nothing reporting.
    nothing_left = ""
    if node is not None and branch and not node.children:
        # the refresh of a branch's page whose node has no children any more
        nothing_left = f"Nothing stands beneath {node.name} now."
    if node is not None and (hide_ok or hide_idle):
        hidden: set[StatusCode] = set()
        if hide_ok:
            hidden.add(StatusCode.OK)
        # hide-idle hides only never-reported (UNDEFINED) nodes; maintenance is an
        # intentional admin state, not idle, and stays visible (the index/pip surface
        # it, so bundling it with idle only made it harder to find).
        if hide_idle:
            hidden.add(StatusCode.UNDEFINED)
        kept = tuple(f for f in (_filter_snapshot(c, hidden) for c in node.children)
                     if f is not None)
        if not kept:
            nothing_left = _nothing_left(node.children,
                                         under=node.name if branch else "")
        node = replace(node, children=kept)
    # The whole tree is drawn, every node open or closed (ADR-0127 decision 1):
    # `depth=N` closes the level N below the page's node, and `depth=0` alone keeps
    # the one-card rendering, the page's node closed to its head and counts.
    depth = _resolve_depth()
    max_depth = 0 if depth == 0 else MAX_DEPTH
    depth_closed = depth if depth else None
    # The first look (ADR-0128, backlog #91 §7.5): how each node the filters leave
    # starts — as its files say, today's density where nobody spoke, the failure
    # budget's openings among them — and what the planner prices of it, which reads
    # no status. `depth=0`'s one card draws no tree. The chips are priced in the face
    # this browser's theme draws them in, as its estimate's length is read.
    drawn = _first_drawn(node, depth_closed) if max_depth >= 1 else Drawn()
    priced = _priced(node, drawn, chip_leaves,
                     chip_face(_presentation()["theme"]))
    # One server-formatted stamp per response (ADR-0006): rendered into the page
    # so it dates its data from the first paint (page JavaScript cannot read
    # navigation-response headers), and sent as X-Rendered-At so the poll loop
    # reads the same clock — "updated …" / "could not refresh — last ok …" honor
    # settings.yaml's time_format and timezone, not the browser's locale. The
    # same clock in whole seconds rides on the grid for the tab's map, which holds
    # a close for its node's incident by the server's time (decision 9).
    rendered_at = _format_local(now)
    rendered_s = int(now.timestamp())
    no_node = _no_node(branch, now) if node is None and branch else None
    # What the hover card says of each node's `about` (ADR-0019), the strip's
    # among them, for the nodes the grid draws: it rides in the fragment, so a node
    # a run names after the load has its card and a changed text is current.
    node_meta = _node_meta_map(node) | _node_meta_map(heartbeat)
    if request.args.get('fragment'):
        body = render_template('_status_grid.html', node=node, branch=branch,
                               no_node=no_node,
                               since=since, made_by=made_by,
                               node_curves=node_curves,
                               # The poll fragment renders the same node block as
                               # the page, so it needs the same facts — without
                               # this the dependent count would vanish ten seconds
                               # after every load and come back on a reload.
                               dependents=(status_tree.dependents(branch)
                                           if branch else ()),
                               max_depth=max_depth, depth_closed=depth_closed,
                               drawn=drawn, priced=priced,
                               hide_ok=hide_ok, hide_idle=hide_idle,
                               chip_counts=chip_counts_by_path,
                               chip_leaves=chip_leaves,
                               rendered_s=rendered_s,
                               is_admin=user.admin,
                               # The fragment carries the page's editors of a pin
                               # (ADR-0104 decision 7), so it is handed what they
                               # print and where they come back to, as the page is.
                               maintenance_default=config.maintenance_default_expiry,
                               maintenance_timezone=config.timezone,
                               here=here, containers=containers,
                               focus=focus, focus_orphan=focus_orphan,
                               pins_above=pins_above,
                               heartbeat=heartbeat, node_meta=node_meta,
                               reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_rows=maintenance_rows,
                               maintenance_ancestors=maintenance_ancestors,
                               nothing_left=nothing_left)
    else:
        body = render_template('status.html', username=user.name,
                               firstname=user.firstname, node=node,
                               no_node=no_node,
                               node_curves=node_curves, view="status",
                               series_tab=_series_tab(branch),
                               series_count=_series_count(branch),
                               dependents=(status_tree.dependents(branch)
                                           if branch else ()),
                               branch=branch, since=since, made_by=made_by,
                               max_depth=max_depth, depth_closed=depth_closed,
                               drawn=drawn, priced=priced,
                               hide_ok=hide_ok, hide_idle=hide_idle,
                               chip_counts=chip_counts_by_path,
                               chip_leaves=chip_leaves,
                               rendered_s=rendered_s,
                               is_admin=user.admin,
                               maintenance_default=config.maintenance_default_expiry,
                               maintenance_timezone=config.timezone,
                               here=here, containers=containers,
                               focus=focus, focus_orphan=focus_orphan,
                               pins_above=pins_above,
                               heartbeat=heartbeat, node_meta=node_meta,
                               rendered_at=rendered_at,
                               reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_rows=maintenance_rows,
                               maintenance_ancestors=maintenance_ancestors,
                               nothing_left=nothing_left)
    response = make_response(body)
    response.headers['X-Rendered-At'] = rendered_at
    response.headers['X-Assets'] = assets_digest()
    # Persist a filter only when the viewer set it explicitly (never on the ~10s
    # poll fragment), so the chosen shape sticks across visits.
    if not request.args.get('fragment'):
        for name, value in (('hide_ok', hide_ok), ('hide_idle', hide_idle)):
            if request.args.getlist(name) or request.args.get('view'):
                response.set_cookie(name, '1' if value else '0',
                                    max_age=VIEW_COOKIE_MAX_AGE, samesite='Lax',
                                    secure=_connection_is_secure())
    # The depth and density cookies the band wrote are no longer read (ADR-0127
    # decision 7): the first answer that finds one expires it, so neither lingers.
    for name in RETIRED_VIEW_COOKIES:
        if name in request.cookies:
            response.delete_cookie(name, samesite='Lax',
                                   secure=_connection_is_secure())
    return response


@app.route('/history/<path:path>')
def history(path: str) -> ResponseReturnValue:
    user = identity.signed_in()
    node = status_tree.snapshot(path)
    if node is None:
        return _no_node_page(user, path)
    periods = list(reversed(status_tree.history(path)))
    # A node that declares nothing above nodes that report has no own status for a
    # period to name (`_declares_nothing`, the Time card's rule): its current period
    # is not a row; the table ends with the last one that named a status, and a line
    # says since when (ADR-0094 decision 5). A leaf's `UNDEFINED` is its own reading
    # and keeps its row, as does one in the past.
    quiet_since: datetime | None = None
    if (node is not None and _declares_nothing(node)
            and periods and periods[0].code is StatusCode.UNDEFINED):
        quiet_since = periods.pop(0).since
    # Where the tree has no period for the node, which quiet it is (ADR-0102
    # decision 3): one that declares nothing of its own says so — in the table, since
    # when where the tree knows — and one nothing is kept of has none yet. A node a
    # check has written always has the period that holds: the tree keeps its
    # beginning, or the bound it began before, where the log no longer holds the
    # row (ADR-0110 decision 5).
    declares_nothing = node is not None and _declares_nothing(node)
    # The rows are the periods of the node's **own** status, as every period is
    # (ADR-0107 decision 1). Where the node has nodes beneath it that is one part
    # of what its page heads with, and the page says so under its table (ADR-0123
    # decision 3) — unless it declares nothing, which the line above already says.
    own_periods = bool(node.children) and not declares_nothing
    return render_template('history.html', username=user.name,
                           firstname=user.firstname, node=node,
                           branch=path, periods=periods,
                           declares_nothing_since=quiet_since,
                           declares_nothing=declares_nothing,
                           own_periods=own_periods,
                           # Every reading kept by each check mounted on the
                           # node, beneath the periods: the page is not polled.
                           readings=_history_readings(node), view="history",
                           series_tab=_series_tab(path),
                           series_count=_series_count(path))


@app.route('/series')
def series_index() -> ResponseReturnValue:
    """The Series index (ADR-0097 decision 4): every node a series is kept on, and
    where a reader goes from it — and, where `Accept` asks for JSON, every series
    the instance keeps (ADR-0122 decision 2)."""
    if _wants_json():
        return _series_json("")
    # Not behind the gate, as `/status` is not (ADR-0122 decision 8): the JSON half
    # above answers a bearer token, so the session is asked for here.
    user = identity.current_user()
    if user is None:
        return identity.challenge()
    return render_template('series_index.html', username=user.name,
                           firstname=user.firstname, node=status_tree.snapshot(""),
                           branch="", index=_series_index(), view="series",
                           series_tab=True, series_count=_series_count(""))


@app.route('/series/<path:path>')
def series(path: str) -> ResponseReturnValue:
    """A node's Series view (ADR-0097 decision 1): every curve that stands at or
    beneath it, on one time axis, and the newest readings they were drawn from. Not
    polled: it is read, as History is. Where `Accept` asks for JSON it is the series
    read: the same series, as data (ADR-0106 decision 6, ADR-0122)."""
    if _wants_json():
        return _series_json(path)
    user = identity.current_user()
    if user is None:
        return identity.challenge()
    node = status_tree.snapshot(path)
    if node is None:
        return _no_node_page(user, path)
    try:
        window = _window(request.args)
    except _WindowRefused as refused:
        abort(400, description=refused.said)
    shown = _series_view(path, window)
    if shown is None:
        abort(404)
    return render_template('series.html', username=user.name,
                           firstname=user.firstname, node=node, branch=path,
                           view="series", series_tab=True,
                           series_count=_series_count(path),
                           window_args=dict(window.written), **shown)


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

    A check with units of its own counts as the period of the node that answers
    at ``path`` (ADR-0130 decision 5): the unit's, where the pin stands at or
    beneath the node a unit answers for, and otherwise — the pin above the units,
    on a container or the mount — the shortest period among the units beneath it,
    which is what that container says it is read on. A pin on an account whose
    aspects run every minute and once a day covers a run of the minute's within
    the hour; it is the daily aspect's own node that needs the day.
    """
    if engine is None:
        return None
    slowest: _IntervalFloor | None = None
    for check in engine.checks:
        seconds = _period_at(check, path)
        if seconds is None or seconds <= 0:
            continue
        if slowest is None or seconds > slowest.seconds:
            slowest = _IntervalFloor(seconds, check.path)
    if slowest is not None and slowest.seconds > MAX_MAINTENANCE_SECONDS:
        return None
    return slowest


def _period_at(check: Check, path: str) -> int | None:
    """What ``check`` says a node at ``path`` is read on, where it covers the
    path at all (:func:`_interval_floor`): the period of the unit answering at or
    above it, else the shortest period of the units beneath it, else ``None`` —
    read off the check's own declaration, `units()`, which for a check that
    declares none is one unit at the mount with the check's `frequency`."""
    if not on_same_line(path, check.path):
        return None
    where = join_path(path)
    above: list[tuple[int, int]] = []
    beneath: list[int] = []
    for unit in check.units():
        node = join_path(check.path, unit.node)
        if where == node or where.startswith(node.rstrip("/") + "/"):
            above.append((len(node), unit.period_seconds))
        elif node.startswith(where.rstrip("/") + "/"):
            beneath.append(unit.period_seconds)
    if above:
        return max(above)[1]
    if beneath:
        return min(beneath)
    return None


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
        # A wall time on purpose (ADR-0120): what an admin typed has no zone of
        # its own, and `_configured_wall_time` gives it the configured one.
        return datetime(year, month, day, hour, minute, second)  # noqa: DTZ001
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
    return candidate.astimezone(UTC)


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
    return now + timedelta(seconds=seconds)


def _maintenance_expiry(raw: str, *, now: datetime | None = None,
                        floor: _IntervalFloor | None = None) -> datetime:
    """Resolve the maintenance form's duration-or-expiry field (ADR-0014).

    ``now`` is captured once by the route and is always compared as an instant.
    Blank uses the configured *duration* default; it is the one value that falls
    back rather than refusing, so a deployment typo cannot make the form unusable
    — and it is held to no ``floor`` for the same reason. Every explicit value is:
    the resolved window has to reach the slowest covered check's next run
    (:func:`_interval_floor`), whichever spelling produced it. All explicit
    calendar shortcuts are resolved in the configured timezone, and what comes
    out is an instant in UTC: the tree stores it as it is (ADR-0120).
    """
    instant = now or instants.now()
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
        return instant + timedelta(seconds=fallback)

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

    An edit's form also says what its expiry field was filled with
    (``expiry_was``): a field that still reads that keeps the stored instant
    exactly, and anything else is read as it was typed (ADR-0104 decision 5). A
    save that then says what the stored pin says changes nothing: the tree writes
    nothing, and the answer is the one a save gets.

    A write returns to **where its block stands**. A form that says where it was
    opened (``next`` — a card on the wall, a branch's head, the Maintenance page)
    goes back there; a leaf's own page says nothing, and gets its page back — for
    one of its lines at the line, by the address that names one
    (``?reason=<slug>#pinned-reason``, ADR-0036 decision 12), since on a node of
    150 lines the top of the page is a long way from the line that was just pinned.
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
    # A card's editor says where it was opened (`next`), so pinning from the
    # wall returns to the wall, and a branch's head to its page as it was asked
    # for; validated like the preferences form's field. Without it — a leaf's
    # page — the node's page stays the destination, which is the page itself: at
    # its top for the node's own pin, whose block stands there, and at the line
    # for a line's.
    next_raw = request.form.get('next', '')
    if next_raw:
        where = _safe_next(next_raw)
    elif slug:
        where = url_for('status', branch=path.lstrip('/'),
                        reason=slug) + '#pinned-reason'
    else:
        where = url_for('status', branch=path.lstrip('/'))
    refused = partial(_maintenance_refused, path=path, slug=slug, back=where,
                      clearing=clearing, mine=typed, duration=duration,
                      token=token or '')
    kept = False
    if clearing and slug:
        write = status_tree.clear_entry_maintenance(path, slug,
                                                    expected_set_at=token)
    elif clearing:
        write = status_tree.clear_maintenance(path, expected_set_at=token)
    else:
        now = instants.now()
        # An edit's expiry field is filled with the stored expiry, and the form
        # says what it was filled with (`expiry_was`). A field that still reads
        # that **keeps the stored instant exactly** (ADR-0104 decision 5): it is
        # not read again, so neither the floor a typed expiry is held to nor the
        # hour a clock change repeats can refuse an edit that left the window
        # alone. The kept value is the pin's the token names — a form that claims
        # nothing is pinned has none, and its field is read like any other.
        was = request.form.get('expiry_was', '').strip()
        kept = bool(token) and bool(was) and duration.strip() == was
        if kept:
            pin = (status_tree.entry_maintenance(path, slug) if slug
                   else status_tree.maintenance_entry(path))
            if pin is None:
                # The pin the field was filled from is gone.
                return refused(problem=None, stored=None, kept=True)
            # Whether this is still the pin the token names is the write's own
            # compare-and-set to say, under the tree's lock; it refuses below.
            expires_at = pin.expires_at
        else:
            try:
                expires_at = _maintenance_expiry(duration, now=now,
                                                 floor=_interval_floor(path))
            except _BadExpiry as bad:
                # Nothing is written and the admin's words come back — the same
                # posture as a refused compare-and-set, for the same reason: a
                # write that silently did something other than what was asked is
                # the thing this route is not allowed to do (ADR-0014). Nothing
                # about the stored pin moved, so what the field was filled with
                # comes back too.
                return refused(problem=str(bad), stored=None, expiry_was=was)
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
        return refused(problem=None, stored=write.current, kept=kept)
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
                         stored: MaintenanceEntry | None,
                         expiry_was: str = "",
                         kept: bool = False) -> ResponseReturnValue:
    """The page a refused write lands on: nothing was saved, here is why, and here
    are your own words back. One page for both refusals — a stale token and a
    duration or expiry we will not accept — because the admin's situation is the same.

    On a bad expiry the form carries the **original** token, because nothing about
    the stored pin moved; a refused compare-and-set is the case that needs a
    refreshed one, and that branch reads it off the entry it is showing.

    The expiry field follows the same split (ADR-0104 decision 5). A bad expiry
    comes back as it was typed, with what the field had been filled with
    (``expiry_was``), which did not move either. ``kept`` says the admin left the
    field as it was filled — they asked for no change to the expiry — so the
    refusal's form is filled again from the pin **as it stands now**, and saving
    their words from there keeps that expiry; where the pin is gone there is
    nothing to keep and the field is a new pin's, empty. An expiry the admin typed
    stays theirs.

    The page is headed by the node's path as every page writes one (``node_path``),
    whichever way the form spelled it: a node's own page posts the route's
    ``branch``, the Maintenance page and the wall the absolute path. Its forms
    post ``path`` back as it came.
    """
    user = identity.signed_in()
    if kept:
        duration = expiry_was = (_expiry_input(stored.expires_at)
                                 if stored is not None else "")
    return render_template(
        'maintenance_conflict.html', username=user.name,
        firstname=user.firstname, path=path, node_path=join_path(path),
        back=back,
        clearing=clearing, stored=stored, slug=slug, problem=problem,
        mine=mine, duration=duration, token=token,
        expiry_was=expiry_was, kept=kept,
        maintenance_default=config.maintenance_default_expiry,
        maintenance_timezone=config.timezone)


@app.route('/maintenance', methods=['GET'])
def maintenance_overview() -> ResponseReturnValue:
    """The full, uncapped maintenance overview as its own page — every pin, node and
    entry alike (ADR-0014, ADR-0036), with what it silences, how long is left, why,
    and who is behind it. Read from the whole snapshot, so it is depth- and
    filter-independent. Viewer-visible and bookmarkable; the strip pill's popover
    "+N more" links here.

    This is the page that has room for **every pin**, which is what makes the
    popover's one-row-per-node summary safe: an admin asking *what is silenced right
    now?* gets a complete answer somewhere. Each pin is the block a node's own page
    states it in, under its node's path, and an admin edits and clears it there
    (ADR-0104 decision 6) — so the page gets what the block's editor prints.

    ``?node=<path>`` names the node a change came from: a save or a clear on this
    page comes back with it, and the page marks that node's section — the
    addressing shape ``?reason=<slug>`` has on a node's own page.

    **A pin whose node is not reported is listed too** (ADR-0109 decision 4), under
    its path and marked as suspended: nothing else shows it, and its block is where
    an admin edits or clears it."""
    user = identity.signed_in()
    now = _now()
    whole = status_tree.snapshot("")
    node_pins, entry_pins, _ = _maintenance_view(whole, now)
    return render_template('maintenance.html', username=user.name,
                           firstname=user.firstname,
                           pins=_maintenance_pins(node_pins, entry_pins,
                                                  _suspended_pins(whole, now)),
                           focus=request.args.get('node', ''),
                           is_admin=user.admin,
                           maintenance_default=config.maintenance_default_expiry,
                           maintenance_timezone=config.timezone)


#: What a row of the Events page says caused it, in a chip beside its status, where
#: a pin did (ADR-0107 decision 3), the node left the tree (ADR-0109 decision 5) or a
#: wait ended by its count — the row that says when a held status reached (ADR-0119
#: decision 3). A reading that changed what its node shows has none: it is what a row
#: is, unless it says otherwise.
_CAUSE_CHIPS: Mapping[str, str] = {
    CAUSE_PIN_SET: "set",
    CAUSE_PIN_EDITED: "edited",
    CAUSE_PIN_ENDED: "maintenance ended",
    CAUSE_LINE_PIN_SET: "line silenced",
    CAUSE_LINE_PIN_ENDED: "line's maintenance ended",
    CAUSE_REMOVED: "removed",
    CAUSE_REACHED: "reached",
}


def _counted(count: int) -> str:
    return f"{count:,} event" + ("" if count == 1 else "s")


def _to_the_minute(moment: datetime) -> str:
    """An instant as a line names it: to the minute, in the configured zone."""
    from little_sister.config import config as settings
    return moment.astimezone(settings.tzinfo).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class _EventsView:
    """What the Events page shows (ADR-0101): the events the window holds that the
    filters keep, newest first; the line that counts them; what the table says when
    it lists none; the window's bar — none for a log with nothing in it — and whether
    anything is set that *reset* would clear."""

    events: tuple[Event, ...]
    line: str
    empty: str
    bar: _WindowBar | None
    anything_set: bool


def _events_view(kept: Sequence[Event], window: _Window,
                 wanted: EventFilter) -> _EventsView:
    """The Events page over ``kept``, the log newest first: the window as the Series
    view reads it, its ends filled from the log's own (ADR-0101 decision 4), an event
    in it when its time is, ends included; and the count and the empty table's
    sentence as decision 5 words them. Every count is over the whole log kept."""
    if not kept:
        return _EventsView((), "", "No events yet.", None, False)
    moments = [event.timestamp for event in kept]
    anything_set = wanted.narrows or bool(window.written)
    if not window.written:
        inside = list(kept)
    else:
        start = window.start or min(moments)
        end = window.end or max(moments)
        inside = [event for event in kept if start <= event.timestamp <= end]
    shown = tuple(event for event in inside if wanted.matches(event))
    if wanted.narrows and inside:
        line = (f"{len(shown):,} of {_counted(len(inside))} "
                + ("matches" if len(shown) == 1 else "match"))
    else:
        line = _counted(len(inside))
    if len(inside) == 0:
        empty = "No events in this window."
    elif len(inside) == 1:
        empty = "The only event in this window does not match."
    else:
        empty = f"None of the {len(inside):,} events in this window match."
    oldest, newest = min(moments), max(moments)
    span = (window.start or oldest, window.end or newest)
    if window.written and span[0] < oldest:
        line += f" · the log reaches back to {_to_the_minute(oldest)}"
    filters = wanted.written()

    def url(written: Mapping[str, str]) -> str:
        values: dict[str, Any] = {**filters, **written}
        return url_for('events', **values)

    return _EventsView(shown, line, empty,
                       _window_bar(url, window, span, (oldest, newest)), anything_set)


@app.route('/events')
def events() -> ResponseReturnValue:
    """The transition log, newest first, narrowed by what its URL names (ADR-0101):
    a node and everything beneath it, words in the reason, the status an event moved
    to, whether a rule held it back, what wrote it — a reading, a pin, a removal
    (ADR-0109 decision 5) — and the window the Series view reads. Nothing remembers
    a filter: ``/events`` alone is always the whole log."""
    user = identity.signed_in()
    try:
        window = _window(request.args)
        wanted = read_filter(request.args)
    except (_WindowRefused, FilterRefused) as refused:
        abort(400, description=refused.said)
    shown = _events_view(tuple(reversed(status_tree.recent_events())), window, wanted)
    existing_paths = {path for path in {event.path for event in shown.events}
                      if status_tree.snapshot(path) is not None}
    return render_template('events.html', username=user.name,
                           firstname=user.firstname, events=shown.events,
                           existing_paths=existing_paths, line=shown.line,
                           empty=shown.empty, bar=shown.bar,
                           anything_set=shown.anything_set, wanted=wanted,
                           status_words=STATUS_WORDS, held_words=HELD_WORDS,
                           cause_words=CAUSE_WORDS, cause_chips=_CAUSE_CHIPS,
                           window_args=dict(window.written))


#: How ``/system/installed`` names a pair's unit, and each kind that has no unit.
_UNIT_NAMES = {"count": "a count", "number": "a number", "duration": "a duration",
               "size": "a size", "amount": "an amount", "share": "a share"}
_KIND_NAMES = {MAP: "a map of words", SET: "a set of accepted values",
               "judgment": "its type's judgment"}


@dataclass(frozen=True)
class GradingRow:
    """One value a type grades, as ``/system/installed`` lists it (ADR-0131
    decisions 1 and 6): its full name — the block it lives in, then its key — its
    sentence, its kind, every key a deployment writes it under in that block, what
    it grades with where nothing is written, and whether a rule of the block may
    write it."""
    name: str
    sentence: str
    kind: str
    keys: tuple[str, ...]
    default: str
    rules: bool

    @classmethod
    def of(cls, grading: Grading) -> 'GradingRow':
        """The row for one declaration: a pair's keys with the ``null`` that
        switches it off last, and a default written as the configuration card writes
        a setting — *warn above 80%, error above 90%* — or a dash where there is
        none."""
        keys = grading.keys
        if grading.kind in (PAIR, SINCE):
            way = "a maximum" if grading.most else "a minimum"
            kind = f"{way}, {_UNIT_NAMES.get(grading.unit, grading.unit)}"
            if grading.kind == SINCE:
                kind = f"the window, {kind}"
            keys = (*keys[1:], f"{keys[0]}: null")
        else:
            kind = _KIND_NAMES.get(grading.kind, grading.kind)
        default = Graded(grading.block, {grading.name: grading.default}).summary(
            grading.name, grading)
        return cls(grading.name, grading.sentence, kind, keys, default or "—",
                   grading.rules)


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
    #: What the type declares of its lines (ADR-0126) — its forms, its words and
    #: its fields — as the checks that name it were built with. Empty for a type no
    #: check names, since a type's declarations are read when one of its checks is
    #: built, and for a type whose lines are sentences of its own.
    lines: Declarations = field(default_factory=Declarations)
    #: What the type declares it grades (ADR-0131), as the checks that name it were
    #: built with — empty, as ``lines`` is, for a type no check names and for one
    #: that grades in its own code alone.
    gradings: tuple[GradingRow, ...] = ()

    @property
    def count(self) -> int:
        """How many checks name this type — the number the row leads with."""
        return len(self.paths)

    @property
    def says(self) -> bool:
        """Whether the type declares anything a ``display:`` block may name."""
        return bool(self.lines.forms or self.lines.words or self.lines.fields)


def _declared_lines(declared: Sequence[Declarations]) -> Declarations:
    """One type's declarations, as its checks were built with them: each form, word
    and field once, in the order the first check to declare it gave — the same for
    every check of a type that declares them as constants, and every name any of
    them declared for one that does not."""
    forms: dict[str, Form] = {}
    words: dict[str, Declared] = {}
    fields: dict[str, Declared] = {}
    for one in declared:
        for form in one.forms:
            forms.setdefault(form.name, form)
        for word in one.words:
            words.setdefault(word.name, word)
        for item in one.fields:
            fields.setdefault(item.name, item)
    return Declarations(tuple(forms.values()), tuple(words.values()),
                        tuple(fields.values()))


def _declared_gradings(declared: Sequence[Sequence[Grading]]
                       ) -> tuple[GradingRow, ...]:
    """One type's gradings, as its checks were built with them: each once, by its
    name, in the order the first check to declare it gave — as
    :func:`_declared_lines` reads its lines."""
    rows: dict[str, GradingRow] = {}
    for one in declared:
        for grading in one:
            if grading.name not in rows:
                rows[grading.name] = GradingRow.of(grading)
    return tuple(rows.values())


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
    declared: dict[str, list[Declarations]] = {}
    graded: dict[str, list[tuple[Grading, ...]]] = {}
    for check in (info.checks if info is not None else ()):
        used.setdefault(check.type_name, []).append(check.path)
        declared.setdefault(check.type_name, []).append(check.line_declarations)
        graded.setdefault(check.type_name, []).append(check.gradings)
    in_use = [TypeRow(origin, tuple(used[origin.type_name]),
                      _declared_lines(declared[origin.type_name]),
                      _declared_gradings(graded[origin.type_name]))
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
    # The noise caps (ADR-0121 decision 7): what a package declared for the
    # dependencies it brings, beside its other registrations — set or not, which
    # is the Logging section's to say. A cap declared from `__main__` names no
    # installation and joins no row; that section lists it all the same.
    for row in noise.rows():
        if row.package:
            registers.setdefault(row.package, set()).add(f"cap {row.logger}")
    return [PackageRow(origin=package_origin(package),
                       registers=tuple(sorted(registers[package])))
            for package in sorted(registers) if package != "little_sister"]


@app.route('/system')
def system() -> ResponseReturnValue:
    """**Running** (ADR-0100): which instance this is, what its engine holds and
    what it runs next — the part of the system the ~10s poll refreshes."""
    user = identity.signed_in()
    if not user.admin:
        abort(403)
    # Same freshness contract as the dashboard (ADR-0005): one server-formatted
    # stamp per response, seeded into the page and sent as X-Rendered-At for
    # the ~10s fragment poll (`fragment=1` returns just the info block).
    rendered_at = _format_local(_now())
    info = engine.info() if engine is not None else None
    if request.args.get('fragment'):
        body = render_template('_system_info.html', info=info)
    else:
        body = render_template('system.html', username=user.name,
                               firstname=user.firstname,
                               version=__version__, info=info,
                               rendered_at=rendered_at,
                               instance=this_instance(),
                               instance_named=bool(config.instance))
    response = make_response(body)
    response.headers['X-Rendered-At'] = rendered_at
    response.headers['X-Assets'] = assets_digest()
    return response


@app.route('/system/installed')
def system_installed() -> ResponseReturnValue:
    """**Installed** (ADR-0100): what this installation settled at startup and
    cannot change while the process runs — so nothing on it is polled.

    The extension seams: which package fills which template slot (ADR-0034), which
    configuration aspects a dependent package added (ADR-0035), and which package
    answers for each secret scheme (ADR-0064). A seam nobody can see from the
    running instance is indistinguishable from one that silently did not take.

    The check-type roster for that reason too, and one more: a type may be
    registered by a separately released package (ADR-0051), so "which code answers
    for `type: github`, at which version" is derivable only from the running
    process. It is split against the engine's checks (`_type_roster`) so the types
    this configuration runs come first and the rest fold away.

    The ways in (ADR-0069 §6), and the assembled policy for the same reason as the
    seams and one more: a source is contributed by a *package*, so a request
    blocked inside somebody else's code is undebuggable from this instance unless
    the page says who asked for each origin (ADR-0048 §7).

    And what each type this configuration runs declares of its lines (ADR-0126):
    the forms its grading names, each with the sentence that says when and its
    default text, and the words and the fields a template may name, each with its
    sentence and an example — the page a deployment writes a ``display:`` block
    against, since a type's declarations live in its package and nowhere a
    deployment can read them.

    And what the log leaves out (ADR-0121 decision 7): whether the library's
    default is in charge of it, the root's level, every logger that carries a
    level of its own with where the level comes from — a cap a package declared,
    an entry of ``LOG_LEVEL``, or neither — and every declared cap that was not
    set, with the reason. Read off the loggers as they stand at the request,
    since what code sets after the import it sets; nothing here polls it.
    """
    user = identity.signed_in()
    if not user.admin:
        abort(403)
    info = engine.info() if engine is not None else None
    in_use, folded = _type_roster(info)
    aspects = [(name, aspect_owner(name)) for name in registered_aspects()]
    return render_template('system_installed.html', username=user.name,
                           firstname=user.firstname, version=__version__,
                           types_in_use=in_use, types_folded=folded,
                           line_types=[row for row in in_use if row.says],
                           grading_types=[row for row in in_use if row.gradings],
                           library_lines=WINDOW_DECLARATIONS,
                           library_gradings=tuple(GradingRow.of(grading)
                                                  for grading in LIBRARY_GRADINGS),
                           slot_fillers=slots.all_fillers(),
                           packages=_registering_packages(),
                           extra_aspects=aspects,
                           resolvers=registered_resolvers(),
                           doors=identity.registered_doors(),
                           choosing_at_login=identity.choosing_at_login(),
                           system_admin=system_admin.registered(),
                           csp_header=CSP_HEADER,
                           csp_directives=csp_policy.directives,
                           csp_links_sources=links_policy_sources(current_links()),
                           log=noise.report())


@app.route('/copy')
@app.route('/copy/<path:branch>')
def copy(branch: str = "") -> ResponseReturnValue:
    """A hand-off as a **page of its own** — the tree, one node, or one reason.

    One route, addressed exactly as ADR-0036 decision 12 settled it for
    maintenance: the node is a **path**, the entry is a **query value**
    (`?reason=<slug>`), never a path segment — a discovered entry's slug contains a
    `/`, and a percent-encoded one does not survive `PATH_INFO`. Four documents
    come of it, since a node with nodes beneath it hands over what is beneath it
    and a leaf what its check read (ADR-0115 decision 5). The page is a view of its
    node (decision 7): it stands in the node's band, under the tabs the node's
    other views carry, and says which document it holds — the tree's in the root's
    band, a line's in its node's. A path no node stands at has no document, and is
    answered as its other addresses are (ADR-0116).

    Each says where it is from and when it was made (decision 1): the address of
    the page it describes as this request reached it, and this moment. And each
    node an outline lists says since when, from the period its own page states
    (decision 2) — one read of the tree's history for each, on a page that is made
    when somebody asks for it and at no other time.

    Why a page rather than a button that copies in place. The per-line control
    lives in the `reason.actions` slot, whose fillers are links; a page keeps it
    one, works with JavaScript off, and — the part that decides it — keeps the
    documents *out of the pages*. The detail page lists every reason uncapped and
    the grid's rail rides the ~10s poll, so a document embedded per line would be
    paid for on every render of the crowded node this feature exists for. Here
    each one is fetched exactly when somebody asks for it.

    No other page carries a document: a node's Status page leads here by its Copy
    tab, a leaf's as a branch's (decision 7).
    """
    user = identity.signed_in()
    style = _copy_style()
    # One immutable read for both representations: the rich HTML is rendered from
    # the canonical Markdown below, so a check update can never put two different
    # incidents on the same page (ADR-0002).
    node = status_tree.snapshot(branch) if branch else None
    # A path no node stands at is answered with the page that says what is known of
    # it, as each of its addresses is (ADR-0116) — and so is a line asked of it.
    if branch and node is None:
        return _no_node_page(user, branch)
    # what the node's band takes on every view of the node (ADR-0097 decision 3)
    band: dict[str, Any] = {"branch": branch, "view": "copy",
                            "series_tab": _series_tab(branch),
                            "series_count": _series_count(branch)}
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
                                   copy_html_text="",
                                   node=node, copy_missing_reason=True,
                                   **band), 404
        if line is not None:
            markdown = format_reason_markdown(node, line, style,
                                              origin=_copy_origin(branch, slug))
            kind = "line"
        else:
            markdown = _node_markdown(branch, node, style)
            kind = "branch" if node.children else "node"
    else:
        # the tree's document, in the root's band
        node = status_tree.snapshot("")
        markdown = format_tree_markdown(node, style, _copy_origin(), _period_of)
        kind = "tree"
    rich = render_markdown(markdown)
    return render_template(
        'text.html', username=user.name,
        firstname=user.firstname, copy_markdown=markdown,
        copy_html=rich, copy_html_text=str(rich),
        node=node, copy_kind=kind, **band)


def _copy_origin(branch: str = "", reason: str = "") -> Origin:
    """Where a Copy document is from and when it was made (ADR-0115 decision 1):
    the address of the page it describes — the wall, a node's page, that page with
    a line marked — and this moment.

    Absolute, as a link back out of a ticket has to be, and so the address this
    request came by: what a proxy or a tunnel was asked for, where one stands in
    front. The jira package's link back is built the same way."""
    if not branch:
        address = url_for('status', _external=True)
    elif reason:
        address = url_for('status', branch=branch, reason=reason, _external=True)
    else:
        address = url_for('status', branch=branch, _external=True)
    return Origin(address, _now())


def _declares_nothing(node: StatusSnapshot) -> bool:
    """Whether ``node`` declares nothing of its own above nodes that report: its own
    code `UNDEFINED`, with children. The roll-up skips that code (ADR-0039) and the
    node's page heads with what its children roll up to, so it has no status for a
    period to name (ADR-0094 decision 5). A leaf's `UNDEFINED` is its own reading."""
    return node.own_code is StatusCode.UNDEFINED and bool(node.children)


def _node_markdown(branch: str, node: StatusSnapshot, style: TimeStyle) -> str:
    """A node's Copy document, at `/copy/<branch>`, its period bounded as its page
    bounds it. It names the node's own page as where it is from, and what it lists
    beneath a branch is dated by the tree's periods (ADR-0115 decisions 1 and 2)."""
    origin = _copy_origin(branch)
    since = _since_of(branch, node)
    if since is None:
        return format_node_markdown(node, style, origin=origin, periods=_period_of)
    return format_node_markdown(node, style, since.at, before=since.before,
                                began=since.began, origin=origin,
                                periods=_period_of)


@dataclass(frozen=True)
class _Since:
    """Where a node's current own-status period begins, as its surfaces state it:
    the instant of the transition that began it, which the tree keeps where the log
    no longer holds the row (ADR-0110 decision 5) — or, ``before``, a bound: the
    furthest back the tree can vouch that nothing changed, taken once and kept
    until the node changes (ADR-0099 decisions 1, 6 and 9, ADR-0102 decision 3).
    ``began`` says what kind of beginning it was, in the words every surface writes
    after the instant, and is empty where a reading began the period and where the
    instant is a bound (:func:`_began`).

    ``status`` is the status the period names, which is the node's **own**, as
    every period is (ADR-0107 decision 1). ``own`` says that a surface names it so,
    *its own status* (ADR-0123 decision 3): the node counts nodes beneath it into
    what it shows, its own status is one part of that, and the period stated as the
    node's would say *ok since Monday* of a branch whose child was red on Tuesday.
    A surface prints the two as they stand here and chooses neither."""
    at: datetime
    before: bool = False
    began: str = ""
    status: StatusCode = StatusCode.UNDEFINED
    own: bool = False


def _began(period: StatusPeriod) -> str:
    """What a period says of how it began, where a pin did it (ADR-0099 decision 8,
    ADR-0107 decision 3): the node began to show its status then, and its check may
    have read it long before, or may not read it at all.

    A period of maintenance says nothing more, however it began. One that follows
    maintenance began where that ended — the node's pin cleared or expired, its
    lines' pins where every line was silenced, or its check's own report. And one a
    line's pin began, set or ended, says which: a silenced line turns a node green,
    and that is no recovery. A period stated by a bound says nothing of how it
    began: the tree did not see it begin, and such a period carries neither what
    the node showed before nor a cause."""
    if period.code is StatusCode.MAINTENANCE:
        return ""
    if period.previous is StatusCode.MAINTENANCE:
        return "when its maintenance ended"
    if period.cause == CAUSE_LINE_PIN_SET:
        return "when a line was silenced"
    if period.cause == CAUSE_LINE_PIN_ENDED:
        return "when a line's maintenance ended"
    return ""


def _since_of(branch: str, node: StatusSnapshot) -> _Since | None:
    """Where the current own-status period of ``node``, the node at ``branch``,
    begins, or ``None`` where there is no period to bound: it declares nothing above
    nodes that report (:func:`_declares_nothing`), or the tree keeps nothing of it —
    a node that shows nothing and never showed anything else. The tree says when
    the period began, from its rows or from what it kept beside them, and whether
    that instant is a bound (:meth:`StatusTree.history`). Every surface that states
    the period — the Time card on either page and in its poll, the Copy document,
    History's row for the period that holds — takes it from here, with the node as
    it is rather than as a filter left it, so none of them can bound a period
    another does not."""
    if _declares_nothing(node):
        return None
    periods = status_tree.history(branch)
    if not periods:
        return None
    current = periods[-1]
    return _Since(current.since, before=current.before, began=_began(current),
                  status=node.own_code, own=node.counts_beneath)


def _period_of(node: StatusSnapshot) -> _Since | None:
    """Since when a node that an outline lists has shown its status: the period its
    own page states (:func:`_since_of`), which is what a Copy document writes
    beside it (ADR-0115 decision 2)."""
    return _since_of(node.path.lstrip("/"), node)


@dataclass(frozen=True)
class _MadeBy:
    """The node beneath a branch that makes what the branch shows, as the branch's
    Time card names it (ADR-0123 decision 3): ``path``, its own, which its name
    links to, and ``name``, the part of it beneath the branch. ``since`` is the
    period its own page states, where that period is of what the branch shows; or
    ``observed``, when it was last observed, where it counts that only because its
    reading went stale and its period is of something else. ``more`` is how many
    other nodes beneath the branch count the branch's code for themselves."""
    path: str
    name: str
    since: _Since | None = None
    observed: datetime | None = None
    more: int = 0


def _made_by(node: StatusSnapshot) -> _MadeBy | None:
    """The node beneath ``node`` that makes what it shows (ADR-0123 decision 3), or
    ``None``: where that is the node's own, where it is a status no one node makes
    — *ok*, *maintenance* — and where no node beneath counts it for itself, as one
    a damping counter holds back does not.

    The node that makes it so counts the code for itself
    (:attr:`StatusSnapshot.own_counted`), and its parent counts it too, as does
    every node up to ``node`` (:attr:`StatusSnapshot.counted`): a branch on the way
    down that only passes the code on is walked through, never named. Of several,
    the one that has counted the code the longest — the first in the tree's order
    of those that began at one instant — from where its period began, as its own
    page states the period (:func:`_since_of`), or, where it counts the code only
    because its own reading went stale, from when it went stale: its last
    observation and its tolerance after it, since its period is of something else.
    Taken from the node before a filter takes its children away, as the period
    is."""
    shown = node.code
    if not node.derived or shown not in (StatusCode.WARN, StatusCode.ERROR):
        return None
    makers: list[tuple[datetime | None, _MadeBy]] = []

    def walk(parent: StatusSnapshot) -> None:
        for child in parent.children:
            if child.counted is not shown:
                continue
            if child.own_counted is shown:
                makers.append(_maker(node, child))
            walk(child)

    walk(node)
    if not makers:
        return None
    longest = min(((at, index) for index, (at, _) in enumerate(makers)
                   if at is not None), default=None)
    _, first = makers[longest[1] if longest is not None else 0]
    return replace(first, more=len(makers) - 1)


def _maker(node: StatusSnapshot,
           child: StatusSnapshot) -> tuple[datetime | None, _MadeBy]:
    """A node beneath ``node`` that counts what ``node`` shows for itself, as
    :func:`_made_by` names it, and since when it has counted that — ``None`` where
    the tree keeps nothing to say it by."""
    name = child.path[len(node.path):].lstrip("/")
    if child.own_stale and child.own_code is not node.code:
        observed = child.timestamp
        tolerance = child.stale_after_seconds
        went = (observed + timedelta(seconds=tolerance)
                if observed is not None and tolerance is not None else None)
        return went, _MadeBy(child.path, name, observed=observed)
    since = _since_of(child.path.lstrip("/"), child)
    return (since.at if since is not None else None,
            _MadeBy(child.path, name, since=since))


@app.route('/links')
def links() -> ResponseReturnValue:
    """The shared toolbox: the deployment's curated links (ADR-0030).

    The configuration is re-read only when the file actually changed, so an
    operator fixing a URL sees it on the next reload and the process keeps the
    history it has in memory.

    Opening the page is also what **triggers** a reachability pass, and only
    when the newest answer is older than the configured interval (ADR-0030 §9).
    The call starts a daemon thread and returns, so the render never
    waits on the network: the page shows what is already in memory, each verdict
    with its own age, and the answers this open triggers land on the next.

    ``icon_names`` is the roster the page's *Icon names* fold shows, with links
    or without: every name a registered pack defines, so whoever writes the file
    reads the marks off the page instead of out of the log. It is the **registry**, not
    :attr:`LinksConfig.icons` — the deployment's own map may name a remote URL or
    suppress a name, and neither has bytes at ``/links/icon``.
    """
    user = identity.signed_in()
    links_config = current_links()
    link_probe.refresh_if_due(links_config)
    # The page allows the hosts its icons load from — the viewer's browser fetches
    # a remote mark and a favicon itself, and the file names them (ADR-0030).
    g.csp_page_policy = csp_policy.adding(
        "img-src", links_policy_sources(links_config))
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
    # The development server's start (ADR-0091); gunicorn's is the hooks module's.
    # A refusal has already said whose the state directory is.
    try:
        start()
    except LeaseRefused:
        raise SystemExit(1) from None
    # use_reloader=False: the reloader runs this module again in a child process,
    # and that would be a second start beside this one.
    app.run(debug=True, use_reloader=False)
