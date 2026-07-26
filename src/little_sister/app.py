import atexit
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from secrets import token_hex

import yaml
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue
from jinja2 import StrictUndefined
from markupsafe import Markup

from little_sister import __version__
from little_sister.api import authenticate, parse_api_tokens, problem, status_envelope
from little_sister.checks import CheckError, parse_duration
from little_sister.config import config
from little_sister.engine import Engine, create_engine
from little_sister.logger import logger
from little_sister.maintenance import MaintenanceStore
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

# How deep the /status tree renders before stopping (the default and the ceiling
# for the user-chosen depth).
MAX_DEPTH = 8
# Remember a viewer's chosen view (depth + the on/off switches) for a year.
VIEW_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


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


@app.template_filter("shorten")
def _shorten(text: object, length: int = 200) -> str:
    string = str(text)
    return string if len(string) <= length else string[:length - 1] + "…"


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
    (config.yaml); ``fmt`` overrides the format (never the timezone) for
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
    """Render an ISO-8601 timestamp in the configured timezone (config.yaml),
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
    """One row of the maintenance index (view-only, ADR-0014): where a pin sits, its
    reason and short title, and a coarse 'time left'."""
    path: str
    title: str
    reason: str
    remaining: str


def _humanize_remaining(seconds: float) -> str:
    """A coarse 'time left' for the maintenance index — the largest one or two units
    (``2d 3h`` / ``5h`` / ``12m`` / ``< 1m``), or ``expired`` once past."""
    total = int(seconds)
    if total <= 0:
        return "expired"
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


def _maintenance_view(
    node: StatusSnapshot | None, now: datetime,
) -> tuple[list[_MaintenancePin], set[str]]:
    """Surface the maintenance side-table (ADR-0014) for the dashboard, read from the
    **unfiltered** snapshot so it survives hide-idle and any render depth: an *index*
    of every pinned node (path, title, reason, time left) and the set of every path
    that is a **proper ancestor** of a pin (for the "contains maintenance" card pip).
    A pinned node shows its own maintenance, so it never appears in the ancestor set.
    """
    index: list[_MaintenancePin] = []
    ancestors: set[str] = set()

    def walk(current: StatusSnapshot) -> bool:
        """Record ``current``'s pin (if any); return whether its subtree holds one."""
        below = False
        for child in current.children:
            if walk(child):
                below = True
        entry = current.maintenance_entry
        if entry is not None:
            try:
                remaining = (
                    datetime.fromisoformat(entry.expires_at) - now).total_seconds()
            except ValueError:
                remaining = 0.0
            index.append(_MaintenancePin(
                path=current.path, title=current.title, reason=entry.reason,
                remaining=_humanize_remaining(remaining)))
        if below and entry is None:
            ancestors.add(current.path)
        return below or entry is not None

    if node is not None:
        walk(node)
    index.sort(key=lambda pin: pin.path)
    return index, ancestors

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

# Load the allowed users from a deployment-controlled location (ADR-0020):
# LITTLE_SISTER_USERS if set, else `users.yaml` in the working directory.
_users_path = os.environ.get("LITTLE_SISTER_USERS", "users.yaml")
try:
    with open(_users_path, encoding="utf-8") as users_file:
        users = yaml.safe_load(users_file)
except FileNotFoundError as exc:
    raise FileNotFoundError(
        f"user list not found at {_users_path!r} — set LITTLE_SISTER_USERS or "
        f"place a users.yaml in the working directory (see users.example.yaml)."
    ) from exc

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
# LITTLE_SISTER_ENGINE=0. A missing/invalid checks directory is non-fatal — the
# web app still serves.
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
    status_tree.restore_maintenance(store.load())
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
        since = periods[-1].since if periods else node.timestamp
        return render_template('check.html', username=session['username'],
                               firstname=session['firstname'], node=node,
                               branch=branch, since=since,
                               is_admin=session.get('admin', False))
    # Lift the engine self-heartbeat into the status strip (ADR-0024) before filtering,
    # so it shows there always — never as a card, never hidden by hide-ok.
    node, heartbeat = _split_heartbeat(node)
    hide_ok = _resolve_flag('hide_ok', False)
    hide_idle = _resolve_flag('hide_idle', False)
    dense = _resolve_flag('dense', True)
    # Surface the maintenance set (ADR-0014) from the *unfiltered* snapshot, so the
    # index and the "contains maintenance" pips survive hide-idle and any depth.
    now = datetime.now()
    maintenance_index, maintenance_ancestors = _maintenance_view(node, now)
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
    # config.yaml's time_format and timezone, not the browser's locale.
    rendered_at = _format_local(now)
    if request.args.get('fragment'):
        body = render_template('_status_grid.html', node=node, branch=branch,
                               max_depth=depth, hide_ok=hide_ok,
                               hide_idle=hide_idle, dense=dense,
                               heartbeat=heartbeat, reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_index=maintenance_index,
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
                               heartbeat=heartbeat, node_meta=node_meta,
                               rendered_at=rendered_at,
                               reason_cap=config.reason_cap,
                               branch_cap=config.branch_cap,
                               maintenance_cap=config.maintenance_cap,
                               maintenance_index=maintenance_index,
                               maintenance_ancestors=maintenance_ancestors)
    response = make_response(body)
    response.headers['X-Rendered-At'] = rendered_at
    # Persist a view choice only when the viewer set it explicitly (never on the
    # ~10s poll fragment), so the chosen shape sticks across visits (slice 5).
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


def _maintenance_seconds(raw: str) -> int:
    """Seconds for a maintenance window: an explicit duration (``2h`` / ``3d``) when
    given, else the configured default (ADR-0014). A bad value falls back to the
    default — there is always a finite expiry."""
    raw = raw.strip()
    try:
        if raw:
            return parse_duration(raw, _DEFAULT_MAINTENANCE_SECONDS)
        return parse_duration(config.maintenance_default_expiry,
                              _DEFAULT_MAINTENANCE_SECONDS)
    except CheckError:
        return _DEFAULT_MAINTENANCE_SECONDS


@app.route('/maintenance', methods=['POST'])
def maintenance() -> ResponseReturnValue:
    if 'username' not in session:
        return redirect('/login')
    if not session.get('admin'):
        abort(403)
    path = request.form['path']
    if request.form.get('action') == 'clear':
        status_tree.clear_maintenance(path)
    else:
        reason = request.form.get('reason', '').strip() or 'maintenance'
        expires_at = datetime.now() + timedelta(
            seconds=_maintenance_seconds(request.form.get('duration', '')))
        status_tree.set_maintenance(path, reason, expires_at=expires_at,
                                    set_by=session.get('username', ''))
    return redirect(url_for('status', branch=path.lstrip('/')))


@app.route('/maintenance', methods=['GET'])
def maintenance_overview() -> ResponseReturnValue:
    """The full, uncapped maintenance overview as its own page — every pinned node with
    its path, time left and reason, read from the whole snapshot (depth- and
    filter-independent, ADR-0014). Viewer-visible and bookmarkable; the strip pill's
    popover "+N more" links here (slice 10)."""
    if 'username' not in session:
        return redirect('/login')
    pins, _ = _maintenance_view(status_tree.snapshot(""), datetime.now())
    return render_template('maintenance.html', username=session['username'],
                           firstname=session['firstname'], pins=pins)


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
        body = render_template('system.html', username=session['username'],
                               firstname=session['firstname'],
                               version=__version__, info=info,
                               rendered_at=rendered_at)
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
    if 'username' in session:
        return render_template('links.html', username=session['username'],
                               firstname=session['firstname'])
    return redirect('/login')


@app.route('/favicon.ico')
def favicon() -> ResponseReturnValue:
    return redirect('/static/favicon.ico')


if __name__ == '__main__':
    # use_reloader=False so the engine isn't started twice in dev.
    app.run(debug=True, use_reloader=False)
