"""Dev WSGI wrapper for the live-demo harness (backlog #25, Mode 2).

Registers the scripted ``demo`` check type through the public ``CHECK_TYPES`` seam
and *then* imports the app — the same import-before-app slot a real deployment uses
(``implementing-checks.md`` §4) — with the engine on and pointed at the demo check
configs. Run it and watch the dashboard move (poll/swap, eruption reflow,
staleness, popovers across swaps):

    uv run gunicorn -w 1 --threads 8 tests.demo_wsgi:app    # open http://localhost:8000
    # or the Flask dev server:
    uv run python tests/demo_wsgi.py

Log in with the committed fixture user (``pan`` / ``12345678``). Single worker: the
engine and the status tree live in-process (ADR-0001).

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
# So `tests` resolves as a package whether launched via gunicorn or as a script.
sys.path.insert(0, str(_REPO_ROOT))

# Point the app at the demo tree and the committed fixture user; hand the JSON API
# a token so the demo can be polled as JSON too. The engine stays ON — the point.
os.environ.setdefault("LITTLE_SISTER_CHECKS_DIR", str(_HERE / "demo_checks"))
os.environ.setdefault(
    "LITTLE_SISTER_USERS", str(_HERE / "fixtures" / "users.yaml"))
os.environ.setdefault("SECRET_KEY", "demo-harness")
os.environ.setdefault("LITTLE_SISTER_API_TOKENS", "demo=demo-token")

# Register the `demo` type before importing the app (which loads + starts the
# engine at import). importlib keeps this a runtime call, so import-sorting can't
# hoist the app import above it — the ordering here is significant.
importlib.import_module("tests.demo_check")

from little_sister.app import app  # noqa: E402

__all__ = ["app"]


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True, use_reloader=False)
