"""Dev WSGI wrapper for the live demo (testing-the-gui.md, Mode 2).

Registers the scripted ``demo`` check type, the door the fixture user signs in
through and this deployment's slot fillers through the public seams, and *then*
imports the app — the same import-before-app slot a real deployment uses
(``implementing-checks.md`` §4) — pointed at the demo check configs. The import
builds the application and starts nothing; the server's start runs the engine
(ADR-0091), which is gunicorn's hooks module or, for the development server, the
call at the bottom of this file. Run it and watch the dashboard move (poll/swap,
eruption reflow, staleness, popovers across swaps):

    uv run gunicorn -w 1 --threads 8 --config python:little_sister.gunicorn_hooks \\
        tests.demo_wsgi:app                      # open http://localhost:8000
    # or the Flask dev server:
    uv run python tests/demo_wsgi.py

Log in with the committed fixture user (``pan`` / ``12345678``). Single worker: the
engine and the status tree live in-process (ADR-0001). What a restart keeps, and the
log, go under ``var/demo/`` rather than into this checkout's own ``var/``, so the demo
runs beside an instance of this checkout; ``LITTLE_SISTER_DEMO_DIR`` names another
directory. ``LITTLE_SISTER_DEMO_OFFSET=36s`` starts every scenario that far into its
cycle, so a start finds the build failed and ``/ci/pipelines`` waiting — what a
restart does to a wait (``tests/demo_check.py``).

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
# The fixture user list is a configuration root of its own, named first: `users` is
# the aspect that does not layer, so the first root declaring it wins whole
# (ADR-0031) — which is how the demo and the suite share one login list without the
# demo tree carrying a second copy.
os.environ.setdefault(
    "LITTLE_SISTER_CONFIG_DIR",
    os.pathsep.join((str(_HERE / "fixtures" / "config"),
                     str(_HERE / "demo_config"))))
os.environ.setdefault("SECRET_KEY", "demo-harness")
os.environ.setdefault("LITTLE_SISTER_API_TOKENS", "demo=demo-token")

# The demo's own directory, and the process's from here on. What a restart keeps —
# the state directory and the lease on it — and the log are paths relative to where a
# process runs, and run from this checkout they would be its own `var/state/` and
# `var/little-sister.log`, which an instance of this checkout keeps: the demo could
# not run beside that instance, whose lease refuses a second writer (ADR-0090), and
# run after it, it would restore that instance's pins, events and series and save its
# own over them. So it runs in `var/demo/` (a tool's output, named by the tool), and
# `LITTLE_SISTER_DEMO_DIR` names another — which is how a test runs the demo without
# writing into the checkout. Nothing in the demo is read relative to it: the
# configuration roots above and `tests` on `sys.path` are absolute.
_DEMO_DIR = Path(os.environ.get("LITTLE_SISTER_DEMO_DIR")
                 or _REPO_ROOT / "var" / "demo")
_DEMO_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(_DEMO_DIR)

# Register the `demo` type before importing the app, whose start builds the engine
# from the check configs. importlib keeps this a runtime call, so import-sorting
# can't hoist the app import above it — the ordering here is significant.
importlib.import_module("tests.demo_check")

# The door the committed fixture user signs in through (ADR-0069): the built-in login
# list, read from the fixture root named first above — the door this repository's
# own `wsgi.py` and the suite's `conftest.py` register too. The library adds no door
# on anybody's behalf, so without this call every page answers 401 and `/login` 404.
local_login = importlib.import_module("little_sister.local_login")
local_login.use_local()

# The **second** layer of the slot demo (ADR-0034/0037). The first needs no code at
# all: `demo_config/actions.yaml` fills both slots through the declarative list
# (ADR-0038), which is what most deployments will ever write. What only a coded
# filler can show is here — a provider that **declines** with ``None``, so a chip is
# present on some reason lines and absent on others; two fillers in one rail, so the
# claim that a configured chip and a coded one land together in one order can be
# looked at rather than believed; and `/ext/<package>/<member>`, the route that
# serves an extension's own stylesheet and script from our origin.
#
# `demo.css` italicizes the node chip: if it is upright, the asset route is broken.
#
# Imported the same way as the check type and for the same two reasons: `tests` only
# resolves as a package because of the sys.path line above, which runs *after* an
# import block would have, and a runtime call cannot be hoisted past the app import.
slots = importlib.import_module("little_sister.slots")
demo_extension = importlib.import_module("tests.demo_extension")
slots.register("reason.actions", "tests.demo_extension", "review_action.html",
               demo_extension.review_action)
slots.register("node.actions", "tests.demo_extension", "node_action.html",
               demo_extension.node_action)
slots.register_assets("tests.demo_extension", "demo.css", "demo.js")

# The third seam a package registers into (ADR-0048): the origin its script *reaches*.
# `'self'` already covers `demo.js` itself, because the asset route serves it from our
# origin — what a policy cannot know is the host it would call. Nothing in the demo
# actually calls it; the point is that `/system` then shows a source whose contributor
# is a package rather than the library, beside one contributed by `demo_config/csp.yaml`
# — and that a contribution made *here*, before the app import, reaches a policy
# assembled *there*, which is the whole of "assembled, never a constant".
csp = importlib.import_module("little_sister.csp")
csp.allow("connect-src", "https://tracker.example.org", by="tests.demo_extension")

from little_sister.app import app  # noqa: E402

__all__ = ["app"]


if __name__ == "__main__":
    # The development server has no hooks module, so its start is called here, as
    # `python -m little_sister.app` calls it (ADR-0091): without it the demo serves
    # a banner saying the engine never started. A refusal has already said whose the
    # state directory is.
    from little_sister.app import start
    from little_sister.lease import LeaseRefused
    try:
        start()
    except LeaseRefused:
        raise SystemExit(1) from None
    app.run(host="127.0.0.1", port=8000, debug=True, use_reloader=False)
