"""Dev-only: measure the settings menu's rendered contrast across the themes.

Mode 4 of the UI harness. Runs a real server, serves the vendored Bootstrap CSS
and JS from disk (the dropdown needs the JS to open at all), and for every theme
opens the gear menu, walks the `/links` rows and the folds of its setup guide, the
**coded reason lines** of a seeded tree, a pin's block with its editor opened — on a
leaf's page, in a card on the wall and in a branch's head — the Maintenance page, and
the chips of the Events page, reading each row's *computed* color and the background it
actually lands on — compositing every translucent layer, folding stacked opacity — then
reports the WCAG ratio.

    npm i --prefix var/bootstrap bootstrap@5.3.2     # once; var/ is gitignored
    uv run python tests/sweep_contrast.py

Why it exists next to ``tests/test_contrast.py``, which measures the same rows
without a browser: **the menu's surface is not ours.** ``.ls-menu__panel`` sets a
width and a padding; the fill comes from Bootstrap's ``--bs-dropdown-bg``, so a
row sits on white in a light theme and on ``#212529`` wherever
``data-bs-theme="dark"`` is set — cyberpunk included, whose ``--ls-panel`` never
reaches it. The gate test has to write those two down; this is what checks them,
against whatever Bootstrap version the templates actually link. Run it when the
theme roster, the menu, or the Bootstrap pin moves.

Exits non-zero if a gated theme misses AA, so it can be wired into a check that
has a browser. Cyberpunk is measured and reported but not gated (ADR-0028).

Not part of the gate: it needs Playwright and a browser. Dev-only, under tests/.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

os.environ.setdefault(
    "LITTLE_SISTER_CONFIG_DIR",
    os.pathsep.join((str(_HERE / "fixtures" / "config"),
                     str(_HERE / "demo_config"))))
os.environ.setdefault("SECRET_KEY", "contrast-sweep")

from little_sister import local_login  # noqa: E402

# The login this sweep signs in through: a door has to be registered before the
# application is imported, and nothing registers one for a script (the suite's
# `conftest.py` does it for the tests, a deployment's `wsgi.py` for itself).
local_login.use_local()

from little_sister import app as app_module  # noqa: E402
from little_sister.app import app  # noqa: E402
from little_sister.links import LinksConfig  # noqa: E402
from little_sister.status import StatusCode  # noqa: E402
from tests.ui_fixtures import coded_workflow_tree  # noqa: E402

# No engine runs — the application is imported and never started (ADR-0091) — so the
# tree the routes read is whatever we put there, and these are the pages a server
# without an engine serves, with no banner saying that nothing started one. Mode 1's
# coded-entry fixture is exactly the page this sweep needs — every tint at once on a
# card that rolled up to ERROR — and sharing it means the sheet you look at and the
# ratios measured here are the same roster (ui_fixtures.coded_workflow_tree).
app_module.engine_error = None
app_module.status_tree = coded_workflow_tree()
CODED_PATH = "ci/actions"          # the seeded node's member leaf page

# Beside the coded card, a branch the wall states a pin on (ADR-0104 decisions 2, 3
# and 7): a box inside a card, pinned — a container, since a pinned leaf is a chip on
# the wall and a chip states nothing — which on its branch's page is a pinned card
# under a head that sets a pin, and states one once the sweep has pinned the branch.
WALL_BRANCH = "storage"
WALL_NOTE = ("Shelf swap, ticket [OPS-77](https://tickets.example.org/OPS-77).\n\n"
             "Back on Monday.")
app_module.status_tree.upsert(f"/{WALL_BRANCH}/nas/disk", StatusCode.OK, "81 % used")
app_module.status_tree.upsert(f"/{WALL_BRANCH}/nas/fan", StatusCode.WARN,
                              "the fan is loud")
app_module.status_tree.set_maintenance(
    f"/{WALL_BRANCH}/nas", WALL_NOTE, set_by="lex",
    expires_at=datetime.now(UTC) + timedelta(days=2))

# And two nodes that wait two readings before they escalate, each read twice at what
# it turned to: the Events page then holds, for an error and for a warning, the row
# the wait held back and the row that says the status reached (ADR-0119).
for _name, _code in (("gateway", StatusCode.ERROR), ("queue", StatusCode.WARN)):
    for _read in (StatusCode.OK, _code, _code):
        app_module.status_tree.upsert(
            f"/waits/{_name}", _read, f"it reads {_read.name.lower()}",
            escalate_after=2)

BOOTSTRAP = _HERE.parent / "var" / "bootstrap" / "node_modules" / "bootstrap" / "dist"
AA = 4.5
UNGATED = {"cyberpunk"}

# (label, theme cookie value, what the OS is telling the browser). `auto` is
# walked twice because only the browser resolves it.
CASES = (
    ("default", "default", "light"),
    ("vivid", "vivid", "light"),
    ("pastel", "pastel", "light"),
    ("dark", "dark", "light"),
    ("auto (OS light)", "auto", "light"),
    ("auto (OS dark)", "auto", "dark"),
    ("cyberpunk", "cyberpunk", "light"),
)

# A row that shows under the pointer only: the wall hides a block's buttons until
# its card is hovered, so at rest there is nothing of them to read.
HOVER_ONLY = "hover only"

# The rows a viewer reads in the open menu, and whether a pointer can wash them.
ROWS = (
    (".ls-menu__heading", False),
    (".ls-menu__item:not(.is-disabled):not(.ls-menu__logout)", True),
    (".ls-menu__item.is-disabled", True),
    (".ls-menu__logout", True),
)

# And the rows on `/links` that are not plain body text: the freshness line, and
# the *check now* button — which wears `btn btn-sm` plus an ink of our own for
# exactly the reason this file exists. Bootstrap's `btn-outline-secondary` paints
# #6c757d on every canvas, which measures 3.76:1 on the dark one; the button was
# written that way first, and this sweep is what said so.
#
# A **verdict** row is not here, nor the freshness line's all-clear green: drawing
# either needs an answer, and whether the demo file's hosts resolve is a property of
# the machine you run this on. Those three inks land on our own canvas rather than
# on a Bootstrap surface, so `tests/test_contrast.py` measures them from the tokens.
#
# The /about hero is not here either, and that one is worth a note: it paints no
# surface at all — it sits on the page canvas — so `tests/test_contrast.py` can
# measure every reading of it from the tokens. What no test can measure is the
# *pairing*: that the term the eyes are on and the phrase it names light
# together. That is what a browser is for; drive the page and watch it.
PAGE_ROWS = (
    (".ls-links__recheck .btn", True),
    (".ls-links__probe", False),
)

# The setup guide's fold at the foot of the same page (ADR-0030). It is a **card**,
# so it stands on a surface Bootstrap paints, as the menu does: its name in the
# card's own ink, and beside it an aside in our muted one — the pair
# `tests/test_contrast.py` remembers, against the two constants this file checks.
FOLD_ROWS = (
    (".ls-links__fold > summary strong", False),
    (".ls-links__fold > summary .ls-links__aside", False),
)

# And the fold opened, the roster of icon names: a paragraph and a `code` in
# Bootstrap's inks on its card, then the table, whose cells Bootstrap fills
# themselves — a head, and a name in the `code` ink again.
ROSTER_ROWS = (
    (".ls-links__fold div.card-body > p", False),
    (".ls-links__fold div.card-body > p code", False),
    (".ls-links__pack thead th", False),
    (".ls-links__pack tbody th code", False),
)

# The other fold, which only a page with no links has: the sample file, a `code`
# in the card's ink on the sheet's own code fill, composited over the card.
SAMPLE_ROWS = (
    (".ls-links__sample code", False),
)

# The coded reason lines (ADR-0042), which are the one row that paints **its own**
# surface: `.is-coded` resets the base reason rule's `opacity: 0.95` to 1 precisely
# so the declared tint pair is the rendered one. `tests/test_contrast.py` measures
# all four pairs from the sheet's own inks and asserts that reset from the
# stylesheet text; what it cannot see is the page — these lines sit *inside* a card
# that rolled up to ERROR and paints a vivid fill of its own, and a pair that is
# right in the tokens can still arrive re-composited. That is the same shape as both
# surfaces this sweep has already found (a Bootstrap dropdown's inherited ink, an
# outline button's #6c757d): right in our tokens, wrong on the page.
#
# No hover state: nothing washes a reason line on hover — the card's hover only
# raises the action chips' opacity — so the rest reading is the whole reading.
CODED_ROWS = (
    (".status-node__reason.is-coded.s-error", False),
    (".status-node__reason.is-coded.s-ok", False),
    (".status-node__reason.is-coded.s-ok.is-running", False),
    (".status-node__reason.is-coded.s-warn", False),
    (".status-node__reason.is-coded.s-undefined", False),
    # The pin's tint outranks the code it covers, which is the louder fact — and it
    # is a *different* pair on the same surface, so it is measured, not assumed.
    (".status-node__reason.is-coded.is-quiet", False),
)

# The same lines on the member leaf page, where the surface under them is the page's
# alert rather than a card fill — a second composite of the same declared pairs, and
# where the uncoded advisory the card folds is visible.
LEAF_ROWS = (
    (".check-reason.is-coded.s-error", False),
    (".check-reason.is-coded.s-ok", False),
    (".check-reason.is-coded.s-warn", False),
    (".check-reason.is-coded.s-undefined", False),
    (".check-reason.is-coded.is-quiet", False),
    (".check-reason:not(.is-coded)", False),
)

# A rule's block on the same page (ADR-0104): the pinned line's statement and its
# note on the block's own tint, the buttons that draw from `currentColor` — *Edit*
# and *Clear* on that tint, and *Set maintenance* on the status line, which is the
# page's alert and so a surface Bootstrap paints, the kind this sweep exists for.
# Their hover moves a border and no fill, and it is walked to keep that true.
BLOCK_ROWS = (
    (".rule-block:not(.rule-block--new) .rule-block__what", False),
    (".rule-block:not(.rule-block--new) .rule-block__note", False),
    (".rule-block__edit > summary", True),
    (".rule-block__clear .rule-button", True),
    (".rule-setter__toggle", True),
)

# And the block's editor, opened: a panel on the panel's own pair inside the tint,
# carrying Bootstrap's labels, its muted help and its link-colored Cancel — three
# inks that are Bootstrap's on a surface that is ours.
EDITOR_ROWS = (
    (".rule-block__edit .rule-block__record", False),
    (".rule-block__edit .form-label", False),
    (".rule-block__edit .form-text", False),
    (".rule-block__edit .maintenance-expiry-help > summary", False),
    (".rule-block__edit .maintenance-editor-cancel", True),
)

# The editor of a pin still to be set says what it covers on the tint itself.
NEW_ROWS = (
    (".rule-setter .rule-block__scope", False),
)

# The same block on the wall (decisions 2 and 7), in a box inside a card: the box
# paints a status fill of its own under the block, which paints its tint over it, so
# the pair is the block's again — measured, like the coded lines above, because a
# pair that is right in the tokens can still arrive re-composited. Its buttons show
# under the pointer only. The first block on the page is the one read.
WALL_ROWS = (
    (".status-node__self > .rule-block .rule-block__what", False),
    (".status-node__self > .rule-block .rule-block__note", False),
    (".status-node__self > .rule-block .rule-block__note a", True),
    (".status-node__self > .rule-block .rule-block__edit > summary", HOVER_ONLY),
    (".status-node__self > .rule-block .rule-block__clear .rule-button", HOVER_ONLY),
)

# The editor a card's pause mark opens in the card (decision 3): what it covers on
# the tint, then Bootstrap's labels, help and Cancel on our panel, as on a leaf's
# page — under a card's head, whose ink and size they must not take.
CARD_EDITOR_ROWS = (
    (".pin-setter .rule-block__scope", False),
    (".pin-setter .form-label", False),
    (".pin-setter .form-text", False),
    (".pin-setter .maintenance-expiry-help > summary", False),
    (".pin-setter .maintenance-editor-cancel", True),
)

# A branch's page: *Set maintenance* in the head, on the head's own fill — a status
# color, and one the block's buttons have not stood on before — and a pinned card's
# block in the card's body.
BRANCH_ROWS = (
    (".viewed-head .rule-setter__toggle", True),
    (".status-panel > .rule-block .rule-block__what", False),
    (".status-panel > .rule-block .rule-block__note", False),
    (".status-panel > .rule-block .rule-block__edit > summary", HOVER_ONLY),
    (".status-panel > .rule-block .rule-block__clear .rule-button", HOVER_ONLY),
)

# And the branch pinned: its block in the head, which shows its buttons always.
HEAD_ROWS = (
    (".viewed-head .rule-block__what", False),
    (".viewed-head .rule-block__note", False),
    (".viewed-head .rule-block__note a", True),
    (".viewed-head .rule-block__edit > summary", True),
    (".viewed-head .rule-block__clear .rule-button", True),
)

# The Maintenance page states the same blocks on the page's canvas (ADR-0104
# decision 6): a line's sentence there carries links — the line's own, and the one
# to the line — which wear the block's ink, and the pin's authors stand under the
# note. The path that heads a node's pins is a link on the canvas itself.
PIN_PAGE_ROWS = (
    (".pin-count", False),
    (".pin-node__path a", True),
    (".pin-node .rule-block__what", False),
    (".pin-node .rule-block__what a", True),
    (".pin-node .rule-block > .rule-block__record", False),
)

# The chips of the Events page, each on a surface of its own inside a row that
# carries a status wash — a table cell Bootstrap paints, on a tint of ours. The row
# that says a wait *reached* wears the pair of the status it shows, one of two
# (ADR-0119 decision 3); the row before it carries the rule that held it back, on
# the maintenance pair every such chip wears.
EVENT_ROWS = (
    (".row-error .event-cause--reached", False),
    (".row-warn .event-cause--reached", False),
    (".row-error .event-suppressed", False),
    (".row-warn .event-suppressed", False),
)

# Read one row as the eye gets it. Two traps are why this is not three lines:
# Chromium reports a color-mix() background as `color(srgb r g b / a)` rather
# than rgba(), and a parser that only knows rgba() silently drops the hover wash
# and reports the rest state twice; and a translucent layer has to be composited
# onto what is under it, not skipped, or the wash never counts.
MEASURE = """
(selector) => {
  const el = document.querySelector(selector);
  if (!el) return {error: 'no such row: ' + selector};
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return {error: 'row not visible: ' + selector};
  const read = (value) => {
    let m = value.match(/rgba?\\(([^)]+)\\)/);
    if (m) {
      const p = m[1].split(',').map(parseFloat);
      return [p[0], p[1], p[2], p.length < 4 ? 1 : p[3]];
    }
    m = value.match(/color\\(srgb\\s+([^)]+)\\)/);
    if (m) {
      const p = m[1].replace('/', ' ').split(/\\s+/).filter(Boolean).map(parseFloat);
      return [p[0] * 255, p[1] * 255, p[2] * 255, p.length < 4 ? 1 : p[3]];
    }
    return null;
  };
  let alpha = 1;
  const layers = [];
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const style = getComputedStyle(n);
    alpha *= parseFloat(style.opacity);
    const layer = read(style.backgroundColor);
    if (!layer || layer[3] <= 0.001) continue;
    layers.push(layer);
    if (layer[3] > 0.999) break;
  }
  let surface = [255, 255, 255];
  for (let i = layers.length - 1; i >= 0; i--) {
    const [r, g, b, a] = layers[i];
    surface = [r * a + surface[0] * (1 - a),
               g * a + surface[1] * (1 - a),
               b * a + surface[2] * (1 - a)];
  }
  const ink = read(getComputedStyle(el).color);
  return {ink: ink.slice(0, 3), alpha: alpha * ink[3], surface: surface};
}
"""


def luminance(rgb: list[float]) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    red, green, blue = (channel(c) for c in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def ratio(ink: list[float], surface: list[float], alpha: float) -> float:
    folded = [ink[i] * alpha + surface[i] * (1 - alpha) for i in range(3)]
    light, dark = sorted((luminance(folded), luminance(surface)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def hexed(rgb: list[float]) -> str:
    return "#" + "".join(f"{min(255, max(0, round(c))):02x}" for c in rgb)


class Quiet(WSGIRequestHandler):
    """The output here is a table to read; an access log buries it."""

    def log_message(self, format: str, *args: object) -> None:
        pass


def serve() -> tuple[WSGIServer, str]:
    server = make_server("127.0.0.1", 0, app, handler_class=Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def main() -> int:
    from playwright.sync_api import Route, sync_playwright

    findings: list[str] = []
    server, base = serve()
    try:
        with sync_playwright() as play:
            # A sandbox pins one browser build; a venv-installed Playwright may
            # expect a different one, so point it at what is there.
            executable = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
            browser = play.chromium.launch(
                executable_path=str(executable) if executable.is_file() else None)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            def vendored(route: Route) -> None:
                name = route.request.url.rsplit("/", 1)[-1]
                for candidate in (BOOTSTRAP / "css" / name, BOOTSTRAP / "js" / name):
                    if candidate.is_file():
                        route.fulfill(path=str(candidate))
                        return
                # Not vendored: let it go to the network rather than measuring an
                # unstyled page and calling it a theme check.
                route.continue_()

            page.route("https://cdn.jsdelivr.net/**", vendored)
            page.goto(f"{base}/login")
            page.fill("#username", "pan")
            page.fill("#password", "12345678")
            page.click("button[type=submit]")

            def walk(label: str, rows: tuple[tuple[str, bool | str], ...],
                     park: str) -> None:
                """Measure one page's rows at rest and, where a pointer reaches
                them, under it — parking on `park` between rows so the wash being
                measured is the row's own."""
                for selector, hoverable in rows:
                    states = (("hover",) if hoverable == HOVER_ONLY
                              else ("rest", "hover") if hoverable else ("rest",))
                    for state in states:
                        if state == "hover":
                            page.hover(selector)
                            page.wait_for_timeout(200)
                        seen = page.evaluate(MEASURE, selector)
                        if "error" in seen:
                            findings.append(f"{label}: {seen['error']}")
                            continue
                        value = ratio(seen["ink"], seen["surface"], seen["alpha"])
                        verdict = "" if value >= AA else "  <-- under AA"
                        if value < AA and label.split()[0] not in UNGATED:
                            findings.append(
                                f"{label} {selector} [{state}] {value:.2f}:1")
                            verdict += " (gated)"
                        print(f"{label:16} {selector[:44]:44} {state:5} "
                              f"{hexed(seen['ink']):9} {hexed(seen['surface']):9} "
                              f"{value:6.2f}{verdict}")
                    page.hover(park)

            print(f"{'theme':16} {'row':44} {'state':5} "
                  f"{'ink':9} {'on':9} {'ratio':>6}")
            print("-" * 100)
            for label, theme, scheme in CASES:
                page.emulate_media(color_scheme=scheme)
                page.context.add_cookies([{
                    "name": "ls_prefs",
                    "value": urlencode({"theme": theme, "layout": "rail"}),
                    "url": base}])
                page.goto(f"{base}/status")
                page.click("#ls-settings")
                page.wait_for_selector(".dropdown-menu.show")
                walk(label, ROWS, "#ls-settings")
                # and the links page, whose rows sit on our own canvas rather than
                # on the surface Bootstrap paints under the menu
                page.goto(f"{base}/links")
                walk(label, PAGE_ROWS, "h1")
                # its guide's fold, closed and then opened — the browser's own
                # disclosure, like a block's editor further down
                walk(label, FOLD_ROWS, "h1")
                page.evaluate(
                    "document.querySelector('.ls-links__fold').open = true")
                walk(label, ROSTER_ROWS, "h1")
                # and the page with no links, whose first fold holds the sample
                configured = app_module.current_links
                app_module.current_links = LinksConfig
                try:
                    page.goto(f"{base}/links")
                    page.evaluate(
                        "document.querySelector('.ls-links__fold').open = true")
                    walk(label, SAMPLE_ROWS, "h1")
                finally:
                    app_module.current_links = configured
                # and the coded lines, on the card fill and then on the leaf page
                page.goto(f"{base}/status")
                walk(label, CODED_ROWS, "#ls-settings")
                page.goto(f"{base}/status/{CODED_PATH}")
                walk(label, LEAF_ROWS, "#ls-settings")
                walk(label, BLOCK_ROWS, "#ls-settings")
                # the editors are the browser's own disclosures, closed at rest
                page.evaluate(
                    "document.querySelector('.rule-block__edit').open = true")
                walk(label, EDITOR_ROWS, "#ls-settings")
                page.evaluate(
                    "document.querySelector('.rule-block__edit').open = false;"
                    "document.querySelector('.rule-setter').open = true")
                walk(label, NEW_ROWS, "#ls-settings")
                page.goto(f"{base}/maintenance")
                walk(label, PIN_PAGE_ROWS, "#ls-settings")
                # and the wall: a pinned box's block, then the editor a card opens
                page.goto(f"{base}/status")
                walk(label, WALL_ROWS, "#ls-settings")
                page.evaluate(
                    "document.querySelector('.pin-setter').open = true")
                walk(label, CARD_EDITOR_ROWS, "#ls-settings")
                # a branch's page, with its head setting a pin and then stating one
                page.goto(f"{base}/status/{WALL_BRANCH}")
                walk(label, BRANCH_ROWS, "#ls-settings")
                app_module.status_tree.set_maintenance(
                    f"/{WALL_BRANCH}", WALL_NOTE, set_by="lex",
                    expires_at=datetime.now(UTC) + timedelta(days=2))
                try:
                    page.goto(f"{base}/status/{WALL_BRANCH}")
                    walk(label, HEAD_ROWS, "#ls-settings")
                finally:
                    app_module.status_tree.clear_maintenance(f"/{WALL_BRANCH}")
                # and the Events page, whose chips stand in rows of a status's wash
                page.goto(f"{base}/events")
                walk(label, EVENT_ROWS, "#ls-settings")
            browser.close()
    finally:
        server.shutdown()

    print("-" * 100)
    for finding in findings:
        print(f"FAIL {finding}")
    print("all gated themes clear AA" if not findings
          else f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
