"""Render the UI-harness fixtures through the real templates (backlog #25, Mode 1).

The *fast loop*. Each extreme fixture (``ui_fixtures.py``) is fed through the
genuine Jinja pipeline — the very ``status.html`` / ``_status_grid.html`` the
server renders, with ``url_for``, the registered template filters and the session
all live — and written as a static HTML page, plus an ``index.html`` linking them.
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
from html import escape
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
# Import the fixtures as a package module whether run as a script or under pytest.
sys.path.insert(0, str(_REPO_ROOT))

# The app loads the user list and (unless disabled) starts the engine at import
# (ADR-0020); point it at the committed test user list and disable the engine so
# importing is side-effect-free — the same setup tests/conftest.py uses.
os.environ.setdefault(
    "LITTLE_SISTER_USERS",
    str(_REPO_ROOT / "tests" / "fixtures" / "users.yaml"))
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "ui-harness")

from flask import render_template, session  # noqa: E402

from little_sister import app as app_module  # noqa: E402
from little_sister.app import (  # noqa: E402
    MAX_DEPTH,
    _node_meta_map,
    _split_heartbeat,
    app,
)
from tests.ui_fixtures import FIXTURES, Fixture  # noqa: E402

_DEFAULT_OUT = _REPO_ROOT / "var" / "ui-harness"
_STATIC_SRC = _REPO_ROOT / "src" / "little_sister" / "static"

# The sheet is a static artifact: a fixed stamp keeps re-runs diffable (the
# live server formats the real time into this slot — ADR-0006).
_RENDERED_AT = "2026-07-20 12:00:00"


def render_page(fixture: Fixture) -> str:
    """Render one fixture's ``status.html`` through the real Jinja pipeline.

    Runs inside a request context so ``url_for`` and ``session`` resolve exactly
    as they do for a live request; the session is set admin so the full nav
    renders. A fixture's ``engine_error`` is installed on the app module for the
    duration of the render (the header banner reads it through the context
    processor) and restored afterwards. Returns the page HTML with
    server-absolute ``/static/`` references left intact —
    :func:`_localize_static` rewrites them per output directory.
    """
    node = fixture.build()
    # Mirror the view: lift the engine heartbeat into the status strip (#24) so
    # the harness renders the strip exactly as a live request does.
    node, heartbeat = _split_heartbeat(node)
    path = f"/status/{fixture.branch}" if fixture.branch else "/status"
    previous_error = app_module.engine_error
    app_module.engine_error = fixture.engine_error
    try:
        with app.test_request_context(path):
            session["username"] = "harness"
            session["firstname"] = "Harness"
            session["admin"] = True
            return render_template(
                "status.html",
                username="harness",
                firstname="Harness",
                node=node,
                branch=fixture.branch,
                max_depth=MAX_DEPTH,
                depth_limit=MAX_DEPTH,
                hide_ok=False,
                hide_idle=False,
                heartbeat=heartbeat,
                node_meta=_node_meta_map(node) | _node_meta_map(heartbeat),
                rendered_at=_RENDERED_AT,
            )
    finally:
        app_module.engine_error = previous_error


def _localize_static(html: str, out_dir: Path) -> str:
    """Rewrite server-absolute ``/static/`` refs to a path relative to ``out_dir``
    that points back at the packaged static dir, so the pages load the *live*
    ``overview.css`` as plain files (no server, no copy)."""
    rel = os.path.relpath(_STATIC_SRC, out_dir)
    return html.replace("/static/", f"{rel.replace(os.sep, '/')}/")


def _index_html(fixtures: tuple[Fixture, ...]) -> str:
    """A minimal contents page linking every rendered fixture."""
    items = "\n".join(
        f'    <li><a href="{escape(f.name)}.html">{escape(f.name)}</a>'
        f' — {escape(f.description)}</li>'
        for f in fixtures
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
