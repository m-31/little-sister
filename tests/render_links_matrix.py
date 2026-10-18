"""Dev-only: render /links across the theme roster and shoot it.

Runs a real server against the demo links configuration, serves the vendored
Bootstrap CSS/JS from disk so the shot is faithful offline, and walks the six
themes × the layouts. Writes PNGs into var/ui-harness/links/.

    npm i --prefix var/bootstrap bootstrap@5.3.2     # once; var/ is gitignored
    uv run python tests/render_links_matrix.py

Bootstrap is vendored **into `var/`** deliberately: an `npm i` in the repo root
would leave `node_modules/`, `package.json` and a lockfile untracked beside the
source, and the release check walks the tree. Without it the page still renders —
the CDN request is simply let through, which needs the network.

Not part of the gate: it needs Playwright and a browser. Dev-only, under tests/.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlencode
from wsgiref.simple_server import WSGIServer, make_server

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

os.environ.setdefault(
    "LITTLE_SISTER_CONFIG_DIR",
    os.pathsep.join((str(_HERE / "fixtures" / "config"),
                     str(_HERE / "demo_config"))))
os.environ.setdefault("SECRET_KEY", "links-matrix")

from little_sister import app as app_module  # noqa: E402
from little_sister.app import app  # noqa: E402
from tests.browser_server import PageServer  # noqa: E402

# Imported and never started (ADR-0091): these are the pages a server without an
# engine serves, so no banner says that nothing started one.
app_module.engine_error = None

THEMES = ("plain", "vivid", "pastel", "dark", "cyberpunk", "auto")
_REPO = _HERE.parent
BOOTSTRAP = _REPO / "var" / "bootstrap" / "node_modules" / "bootstrap" / "dist"


def serve() -> tuple[WSGIServer, str]:
    server = make_server("127.0.0.1", 0, app, server_class=PageServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def main(out: Path) -> None:
    from playwright.sync_api import Route, sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    server, base = serve()
    try:
        with sync_playwright() as play:
            # The sandbox pins one browser build; a venv-installed Playwright
            # may expect a different one, so point it at what is there.
            executable = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            browser = play.chromium.launch(
                executable_path=str(executable) if executable.is_file() else None)
            page = browser.new_page(viewport={"width": 1280, "height": 900},
                                    device_scale_factor=2)

            def vendored(route: Route) -> None:
                # The pages link Bootstrap from a CDN; serve it from disk so the
                # shot is faithful with no network (the dropdown needs the JS).
                name = route.request.url.rsplit("/", 1)[-1]
                for candidate in (BOOTSTRAP / "css" / name, BOOTSTRAP / "js" / name):
                    if candidate.is_file():
                        route.fulfill(path=str(candidate))
                        return
                # Not vendored: let it go to the network rather than shooting an
                # unstyled page and calling it a theme check.
                route.continue_()

            page.route("https://cdn.jsdelivr.net/**", vendored)
            page.goto(f"{base}/login")
            page.fill("#username", "pan")
            page.fill("#password", "12345678")
            page.click("button[type=submit]")

            for theme in THEMES:
                for layout in ("rail", "topbar"):
                    page.context.add_cookies([{
                        "name": "ls_prefs",
                        "value": urlencode({"theme": theme, "layout": layout}),
                        "url": base}])
                    page.goto(f"{base}/links")
                    page.wait_for_timeout(350)
                    shot = out / f"links-{theme}-{layout}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    print(shot)
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1
         else _HERE.parent / "var" / "ui-harness" / "links")
