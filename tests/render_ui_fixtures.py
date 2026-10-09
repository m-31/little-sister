"""Render the fixtures through the real templates (testing-the-gui.md, Mode 1).

The *fast loop*. Each extreme fixture (``ui_fixtures.py``) is fed through the
genuine Jinja pipeline — the very ``status.html`` / ``_status_grid.html`` the
server renders, with ``url_for``, the registered template filters and the session
all live — and written as a static HTML page. The multi-front incident also renders
through the real Copy page, and ``index.html`` links the whole sheet.
Open the index, screenshot, and compare a CSS or template variant across every
fixture in one glance. Because it is the *real* templates, a variant that wins
here is most of the implementation.

    uv run python tests/render_ui_fixtures.py [--out DIR]

Output defaults to ``var/ui-harness/`` (git-ignored) and is never committed. The
pages reference the packaged stylesheet by a **relative** path back into
``src/little_sister/static``, so editing ``static/css/overview.css`` and
re-running shows the change immediately, and the sheet stays viewable as plain
files (no server).

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Import the fixtures as a package module whether run as a script or under pytest.
sys.path.insert(0, str(_REPO_ROOT))

# The app loads the user list at import (ADR-0020); point it at the committed
# fixture root — the same path-list tests/conftest.py builds, set here too so this
# stays runnable as a script (the cwd `config/` has no committed user list —
# `config/users/` is git-ignored). The import starts nothing (ADR-0091), and each
# fixture installs the engine error its page shows.
os.environ.setdefault(
    "LITTLE_SISTER_CONFIG_DIR",
    os.pathsep.join((str(_REPO_ROOT / "tests" / "fixtures" / "config"),
                     str(_REPO_ROOT / "config"))))
os.environ.setdefault("SECRET_KEY", "ui-harness")

from flask import render_template, session  # noqa: E402

from little_sister import app as app_module  # noqa: E402
from little_sister.app import (  # noqa: E402
    MAX_DEPTH,
    _containers,
    _copy_origin,
    _copy_style,
    _maintenance_rows,
    _maintenance_view,
    _node_curves,
    _node_meta_map,
    _series_tab,
    _split_heartbeat,
    app,
)
from little_sister.copy_status import format_tree_markdown  # noqa: E402
from little_sister.render import render_markdown  # noqa: E402
from tests.ui_fixtures import FIXTURES, FIXTURES_BY_NAME, Fixture  # noqa: E402

_DEFAULT_OUT = _REPO_ROOT / "var" / "ui-harness"
_STATIC_SRC = _REPO_ROOT / "src" / "little_sister" / "static"

# The sheet is a static artifact: a fixed stamp keeps re-runs diffable (the
# live server formats the real time into this slot — ADR-0006).
_RENDERED_AT = "2026-07-20 12:00:00"


def render_page(fixture: Fixture) -> str:
    """Render one fixture through the real status/detail Jinja pipeline.

    Runs inside a request context so ``url_for`` and ``session`` resolve exactly
    as they do for a live request; the session is set admin so the full nav
    renders. A fixture's ``engine_error`` is installed on the app module for the
    duration of the render (the header banner reads it through the context
    processor) and restored afterwards. ``fixture.detail`` selects the member
    leaf's ``check.html`` instead of the overview's ``status.html``. Returns the
    page HTML with server-absolute ``/static/`` references left intact —
    :func:`_localize_static` rewrites them per output directory.
    """
    node = fixture.build()
    # Mirror the view: lift the engine heartbeat into the status strip (ADR-0024) so
    # the harness renders the strip exactly as a live request does.
    node, heartbeat = _split_heartbeat(node)
    node_pins, entry_pins, maintenance_ancestors = _maintenance_view(
        node, datetime.now(UTC))
    maintenance_rows = _maintenance_rows(node_pins, entry_pins)
    path = f"/status/{fixture.branch}" if fixture.branch else "/status"
    previous_error = app_module.engine_error
    app_module.engine_error = fixture.engine_error
    # The series the node's facts show come from the engine, as on a live page; a
    # fixture that has one lends it for the render, and every other has none.
    previous_engine = app_module.engine
    app_module.engine = fixture.engine() if fixture.engine is not None else None
    try:
        with app.test_request_context(path):
            session["username"] = "harness"
            session["firstname"] = "Harness"
            session["admin"] = True
            template = "check.html" if fixture.detail else "status.html"
            return render_template(
                template,
                username="harness",
                firstname="Harness",
                node=node,
                branch=fixture.branch,
                dependents=fixture.dependents,
                max_depth=MAX_DEPTH,
                depth_limit=MAX_DEPTH,
                hide_ok=False,
                hide_idle=False,
                dense=fixture.dense,
                is_admin=True,
                maintenance_default=app_module.config.maintenance_default_expiry,
                maintenance_timezone=app_module.config.timezone,
                # What a pin's editor in a card says and comes back to, as the
                # view hands them over.
                here=path,
                containers=_containers(node),
                heartbeat=heartbeat,
                node_meta=_node_meta_map(node) | _node_meta_map(heartbeat),
                rendered_at=_RENDERED_AT,
                reason_cap=(fixture.reason_cap if fixture.reason_cap is not None
                            else app_module.config.reason_cap),
                branch_cap=app_module.config.branch_cap,
                maintenance_cap=app_module.config.maintenance_cap,
                maintenance_rows=maintenance_rows,
                maintenance_ancestors=maintenance_ancestors,
                # Bounds the current status period in the node-facts block's Time
                # card (ADR-0044) — the branch page's now as well as the leaf
                # page's. A fixture is a hand-built snapshot with no transition log
                # behind it, so there is no period to bound and the card reports
                # the single observation instead.
                since=None,
                # And names no node beneath it that makes what it shows, whose
                # period is in the same log (ADR-0123 decision 3): the card's
                # first line, where it has one, says *from the nodes beneath it*.
                made_by=None,
                focus="",
                focus_orphan=None,
                # A hand-built snapshot has no tree above it to hold a pin.
                pins_above=[],
                # The curves that stand on the node (ADR-0097 decision 2), where a
                # fixture's engine keeps a series, and the views beside this one.
                node_curves=_node_curves(node) if fixture.branch else None,
                view="status", series_tab=_series_tab(fixture.branch),
            )
    finally:
        app_module.engine_error = previous_error
        app_module.engine = previous_engine


def render_copy_page() -> str:
    """Render the Copy page with the realistic multi-front incident fixture."""
    with app.test_request_context("/copy"):
        root = FIXTURES_BY_NAME["wall_incident"].build()
        markdown = format_tree_markdown(root, _copy_style(), _copy_origin())
        rich = render_markdown(markdown)
        session["username"] = "harness"
        session["firstname"] = "Harness"
        session["admin"] = True
        # in the root's band, as the route draws the tree's page (ADR-0115 decision 7)
        return render_template(
            "text.html", username="harness", firstname="Harness",
            copy_markdown=markdown, copy_html=rich,
            copy_html_text=str(rich), copy_kind="tree",
            node=root, branch="", view="copy")


def _localize_static(html: str, out_dir: Path) -> str:
    """Rewrite server-absolute ``/static/`` refs to a path relative to ``out_dir``
    that points back at the packaged static dir, so the pages load the *live*
    ``overview.css`` as plain files (no server, no copy)."""
    rel = os.path.relpath(_STATIC_SRC, out_dir)
    return html.replace("/static/", f"{rel.replace(os.sep, '/')}/")


def _index_html(fixtures: tuple[Fixture, ...]) -> str:
    """A minimal contents page linking every rendered fixture."""
    status_items = "\n".join(
        f'    <li><a href="{escape(f.name)}.html">{escape(f.name)}</a>'
        f' — {escape(f.description)}</li>'
        for f in fixtures
    )
    items = (
        '    <li><a href="copy_status.html">copy_status</a>'
        ' — the multi-front incident through the Copy page</li>\n'
        f"{status_items}"
    )
    return (
        "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
        "<title>UI harness — fixtures</title>"
        "<style>body{font:16px/1.5 system-ui,sans-serif;margin:2rem;max-width:60rem}"
        "code{background:#f2f2f2;padding:.1em .3em;border-radius:3px}</style>"
        "</head><body>\n"
        "<h1>UI prototyping harness — fixture sheet</h1>\n"
        "<p>Each link renders an extreme case through the real templates. Edit "
        "<code>src/little_sister/static/css/overview.css</code> (or a template), "
        "re-run <code>tests/render_ui_fixtures.py</code>, and refresh to compare.</p>\n"
        f"<ul>\n{items}\n</ul>\n</body></html>\n"
    )


def render_all(out_dir: Path) -> list[Path]:
    """Render every fixture plus the index into ``out_dir``; returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fixture in FIXTURES:
        page = _localize_static(render_page(fixture), out_dir)
        target = out_dir / f"{fixture.name}.html"
        target.write_text(page, encoding="utf-8")
        written.append(target)
    copy_page = out_dir / "copy_status.html"
    copy_page.write_text(
        _localize_static(render_copy_page(), out_dir), encoding="utf-8")
    written.append(copy_page)
    index = out_dir / "index.html"
    index.write_text(_index_html(FIXTURES), encoding="utf-8")
    written.append(index)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=_DEFAULT_OUT,
        help=f"output directory (default: {_DEFAULT_OUT})")
    args = parser.parse_args(argv)
    written = render_all(args.out)
    print(f"wrote {len(written)} file(s) to {args.out}")
    print(f"open {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
