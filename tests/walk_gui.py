"""Walk the pages as a reader does, and say what did not hold.

Mode 6 of the UI harness (``docs/testing-the-gui.md``). The other modes each hold
one claim; this one goes looking. It starts the live demo (``tests/demo_wsgi.py``)
on a port of its own, renders the fixture sheet beside it, and drives headless
Chromium over both at three widths and on an emulated phone: the wall, a branch's
page and a leaf's, the Series index with its folds open and a Series view, a
subject's node and its runs' marks, Events, Maintenance, History, System, Links and
Copy; it rests on every card head's name, which raises the inspection card where a
node has one — its browser chooses the card on a pause (:data:`CHOSEN_LOOKS`) — drags a
stretch across a curve, and pins the demo's job name that comes and goes, so that what
a removed node leaves — its event, its suspended pin, its kept readings — is on the
pages it visits last.

Every step leaves a screenshot and what the browser said while it was taken: the
console's errors, the Content-Security-Policy reports the page sent, and how far its
layout shifted. And every step is **measured** against a short list of facts
(:data:`FACTS`) — a popover inside the screen, a page no wider than it, nothing
overlapping in a card's head, a curve's marks inside its plot. A fact that does not
hold **marks** the step. Nothing fails: a review collects, and the walk always ends
with a gallery, the marked steps first::

    npm i --prefix var/bootstrap bootstrap@5.3.2 \\
        @floating-ui/core@1.6.8 @floating-ui/dom@1.6.12     # once; var/ is gitignored
    uv sync --group browser
    uv run python tests/walk_gui.py                          # → var/gui-walk/index.html

A fact that is fixed moves into a test of Mode 5, which is where a claim is held;
``tests/test_walk_gui.py`` holds the facts themselves, each seen marking a page
that is broken in its way and passing one that is not.

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import argparse
import contextlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_DEFAULT_OUT = _REPO_ROOT / "var" / "gui-walk"

#: What the pages load from a CDN, vendored as Mode 4 vendors Bootstrap: a URL of
#: ``cdn.jsdelivr.net/npm/<package>@<version>/<path>`` is answered from here where
#: the file is, so a walk needs no network and measures no unstyled page.
VENDORED = _REPO_ROOT / "var" / "bootstrap" / "node_modules"
_CDN = re.compile(r"https://cdn\.jsdelivr\.net/npm/((?:@[^/@]+/)?[^/@]+)@[^/]+/(.+)")

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: How far a page's layout may shift during a step before the step is marked: the
#: line web vitals draws between a layout that is stable and one that needs work.
SHIFT_LIMIT = 0.1


@dataclass(frozen=True)
class Profile:
    """A screen the walk is taken on."""
    name: str
    width: int
    height: int
    phone: bool = False

    def context(self) -> dict[str, Any]:
        """What a browser context is opened with for it."""
        drawn_in: dict[str, Any] = {
            "viewport": {"width": self.width, "height": self.height},
            "reduced_motion": "reduce"}
        if self.phone:
            drawn_in |= {
                "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
                "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/126.0.0.0 Mobile Safari/537.36")}
        return drawn_in


#: Three widths of a desk — a wide screen, a laptop's window, a window beside
#: another — and a phone.
PROFILES = (Profile("desk-1440", 1440, 900), Profile("desk-1000", 1000, 800),
            Profile("desk-700", 700, 800), Profile("phone-390", 390, 800, phone=True))

#: The looks the walk's browser chooses on the demo, as a viewer does in the settings
#: menu (ADR-0029): the inspection card on a pause, which the walk raises on every
#: card head, where the library's look keeps it off since 2026-10-18
#: (``little_sister.looks``). Every other look is the library's.
CHOSEN_LOOKS = {"inspection_card": "pause"}


def open_context(browser: Any, profile: Profile, base: str,
                 chosen: Mapping[str, str] = CHOSEN_LOOKS) -> Any:
    """A browser context of ``profile``'s screen for ``base``'s pages, the looks
    ``chosen`` — the walk's own, :data:`CHOSEN_LOOKS`, unless ``--look`` adds to them —
    in the presentation cookie."""
    context = browser.new_context(**profile.context())
    context.add_cookies([{"name": "ls_prefs", "url": base,
                          "value": urlencode(dict(chosen))}])
    return context


def chosen_looks(asked: Sequence[str]) -> dict[str, str]:
    """The walk's looks and those ``--look`` asks for, each ``key=value`` a look and a
    value of the settings menu's (``little_sister.looks``) — another look under
    which to walk the demo, such as ``boxes=packed``."""
    from little_sister.looks import LOOKS_BY_KEY
    chosen = dict(CHOSEN_LOOKS)
    for item in asked:
        key, _, value = item.partition("=")
        look = LOOKS_BY_KEY.get(key.strip())
        if look is None or value.strip() not in look.values:
            known = ", ".join(sorted(LOOKS_BY_KEY))
            raise SystemExit(f"--look {item!r}: a look and one of its values, "
                             f"key=value, of {known}")
        chosen[look.key] = value.strip()
    return chosen


#: The facts a step is measured against: a name, what it holds a page to, and a
#: script that answers every place the page does not hold it — an empty list where
#: it does. Each is a function of the document alone, so a test can hand it a page
#: broken in its way (``tests/test_walk_gui.py``).
FACTS: dict[str, tuple[str, str]] = {
    "page-width": (
        "A page is no wider than its screen.",
        """() => {
            const over = document.documentElement.scrollWidth - window.innerWidth;
            return over > 1 ? [`the page is ${over}px wider than its screen`] : [];
        }"""),
    "popover-on-screen": (
        "A card that is raised over the page stands inside the screen.",
        """() => {
            const found = [];
            for (const card of document.querySelectorAll(
                    '#inspect-card, #maintenance-card')) {
                const box = card.getBoundingClientRect();
                if (box.width === 0 || box.height === 0) { continue; }
                const out = [];
                const past = (by, side) => {
                    if (by > 1) { out.push(`${Math.round(by)}px past the ${side}`); }
                };
                past(-box.left, 'left');
                past(-box.top, 'top');
                past(box.right - window.innerWidth, 'right');
                past(box.bottom - window.innerHeight, 'bottom');
                if (out.length) { found.push(`#${card.id} stands ${out.join(', ')}`); }
            }
            return found;
        }"""),
    "head-overlap": (
        "In a head's row the name, the title, the actions, the state and the icons "
        "do not lie over one another as a reader sees them, but for a shown toolbar "
        "over the title where the look `head_buttons` lays it there.",
        """() => {
            const found = [];
            // What a reader sees: a part the page hides, or fades by its own opacity
            // or an ancestor's — the pointer looks fade a head's whole toolbar, its
            // `.node-controls`, until the pointer rests on the head — is none.
            const shown = (el) => {
                const style = getComputedStyle(el);
                const box = el.getBoundingClientRect();
                if (style.visibility === 'hidden' || style.display === 'none'
                        || box.width <= 0 || box.height <= 0) { return false; }
                for (let up = el; up && up !== document.body; up = up.parentElement) {
                    if (Number(getComputedStyle(up).opacity) <= 0.05) { return false; }
                }
                return true;
            };
            // Under `pointer` and `pointer-name`, where a pointer can rest on a head,
            // the toolbar takes no room in the row and, shown, lies over the title on
            // purpose (ADR-0127 decision 3): that one overlap is no mark.
            // A head being measured or crowded keeps the toolbar's room, as a touch
            // screen does, so there it marks as everywhere else.
            const overTitle = document.body.matches(
                    '[data-ls-head-buttons="pointer"], '
                    + '[data-ls-head-buttons="pointer-name"]')
                && window.matchMedia('(hover: hover)').matches;
            const ofToolbar = (el) => el.matches(
                '.node-controls > .node-icons, .node-controls > .node-actions > *,'
                + ' .node-controls > .node-more');
            const laid = (head, a, b) => overTitle
                && !head.matches('.is-measuring, .is-crowded')
                && ((ofToolbar(a) && b.matches('.status-head__middle'))
                    || (ofToolbar(b) && a.matches('.status-head__middle')));
            // A name is its lines, not its box: where it broke onto a second line,
            // the state may stand on that line beside it (ADR-0127 decision 3).
            const rectsOf = (el) => {
                if (el.matches('.status-card__name, .status-node__name')) {
                    const range = document.createRange();
                    range.selectNodeContents(el);
                    const lines = Array.from(range.getClientRects())
                        .filter((r) => r.width > 0 && r.height > 0);
                    if (lines.length) { return lines; }
                }
                return [el.getBoundingClientRect()];
            };
            for (const head of document.querySelectorAll(
                    '.status-card__head, .tree-box > .status-node__self')) {
                // The row's parts: the name, the title, the state cluster, and the
                // toolbar's — the icons, ↗ first, then the node's actions and ⋯ —
                // where the look `head_buttons` keeps them (ADR-0127 decision 3).
                const parts = Array.from(head.querySelectorAll(
                    ':scope > .status-card__name, :scope > .status-node__name,'
                    + ' :scope > .status-head__middle,'
                    + ' :scope > .node-controls > .node-actions > *,'
                    + ' :scope > .node-controls > .node-more,'
                    + ' :scope > .status-card__state,'
                    + ' :scope > .status-node__state,'
                    + ' :scope > .node-controls > .node-icons')).filter(shown);
                for (let i = 0; i < parts.length; i += 1) {
                    for (let j = i + 1; j < parts.length; j += 1) {
                        if (laid(head, parts[i], parts[j])) { continue; }
                        let over = null;
                        for (const a of rectsOf(parts[i])) {
                            for (const b of rectsOf(parts[j])) {
                                const wide = Math.min(a.right, b.right)
                                    - Math.max(a.left, b.left);
                                const tall = Math.min(a.bottom, b.bottom)
                                    - Math.max(a.top, b.top);
                                if (wide > 2 && tall > 2 && !over) {
                                    over = [wide, tall];
                                }
                            }
                        }
                        if (over) {
                            const name = (el) => el.className.toString().split(' ')[0]
                                || el.tagName.toLowerCase();
                            found.push(`${head.dataset.path}: .${name(parts[i])} and `
                                + `.${name(parts[j])} overlap by `
                                + `${Math.round(over[0])}×${Math.round(over[1])}px`);
                        }
                    }
                }
            }
            return found;
        }"""),
    "box-overlap": (
        "In a level of boxes — the wall's cards, a card's open boxes — no box stands "
        "over another.",
        """() => {
            const found = [];
            const named = (el) => el.dataset.node
                || '.' + (el.className.toString().split(' ')[0]
                          || el.tagName.toLowerCase());
            for (const level of document.querySelectorAll(
                    '.status-grid, .status-card .node-children')) {
                if (getComputedStyle(level).display !== 'grid') { continue; }
                // a wrapper drawn without a box of its own stands its child in the grid
                const items = [];
                for (const child of level.children) {
                    const display = getComputedStyle(child).display;
                    if (display === 'none') { continue; }
                    if (display === 'contents') { items.push(...child.children); }
                    else { items.push(child); }
                }
                const boxes = items.map((el) => [el, el.getBoundingClientRect()])
                    .filter(([, box]) => box.width && box.height);
                for (let i = 0; i < boxes.length; i += 1) {
                    const [one, a] = boxes[i];
                    for (let j = i + 1; j < boxes.length; j += 1) {
                        const [other, b] = boxes[j];
                        const wide = Math.min(a.right, b.right)
                            - Math.max(a.left, b.left);
                        const tall = Math.min(a.bottom, b.bottom)
                            - Math.max(a.top, b.top);
                        if (wide > 2 && tall > 2) {
                            found.push(`${named(one)} and ${named(other)} overlap `
                                + `by ${Math.round(wide)}×${Math.round(tall)}px`);
                        }
                    }
                }
            }
            return found;
        }"""),
    "curve-in-plot": (
        "Everything a curve draws stands inside its plot.",
        """() => {
            const found = [];
            for (const plot of document.querySelectorAll(
                    'svg.ls-curve__plot, svg.ls-spark')) {
                const view = plot.viewBox.baseVal;
                if (!view || view.width === 0) { continue; }
                // a stroke and a head reach a few units past the point they mark
                const room = plot.matches('.ls-spark') ? 1 : 8;
                for (const mark of plot.querySelectorAll(
                        'path:not(.ls-curve__grid), circle, line.ls-curve__none')) {
                    const box = mark.getBBox();
                    if (box.x < view.x - room || box.y < view.y - room
                            || box.x + box.width > view.x + view.width + room
                            || box.y + box.height > view.y + view.height + room) {
                        const around = plot.closest('li, figure');
                        const label = plot.getAttribute('aria-label')
                            || (around && around.textContent.trim().slice(0, 40))
                            || 'a curve';
                        found.push(`${label}: a .${mark.className.baseVal} `
                            + 'leaves the plot');
                        break;
                    }
                }
            }
            return found;
        }"""),
}

#: Installed before a page's own scripts: every layout shift no input caused is
#: added up where the walk reads it, step by step. A shift whose every source is a
#: card raised over the page is left out: the inspection card is one element, moved
#: from the node it was raised for to the next and kept in place while the page
#: scrolls beneath it, and a browser counts each move as a shift of the layout —
#: which nothing in the layout made. Pointing at one head after another marked a
#: step that way at 700 pixels, where the card is a large share of the screen.
_SHIFT_WATCH = """
window.__lsWalkShift = 0;
try {
    const raised = (source) => source.node && source.node.nodeType === 1
        && source.node.closest('#inspect-card, #maintenance-card') !== null;
    new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
            const sources = entry.sources || [];
            if (entry.hadRecentInput) { continue; }
            if (sources.length && sources.every(raised)) { continue; }
            window.__lsWalkShift += entry.value;
        }
    }).observe({type: 'layout-shift', buffered: true});
} catch (e) { /* a browser without the entry type measures no shift */ }
"""


@dataclass
class Step:
    """One thing the walk did on one screen, and what it found."""
    profile: str
    name: str
    url: str
    shot: str = ""
    #: By fact: each place the page did not hold it.
    findings: dict[str, list[str]] = field(default_factory=dict)
    note: str = ""

    @property
    def marked(self) -> bool:
        return bool(self.findings)


def vendored(url: str, root: Path = VENDORED) -> Path | None:
    """The vendored file a CDN URL names, or ``None`` where it is not vendored —
    or is not a file beneath the vendored root, whatever the URL says."""
    found = _CDN.fullmatch(url.split("?", 1)[0])
    if found is None:
        return None
    candidate = (root / found.group(1) / found.group(2)).resolve()
    if root.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def csp_said(body: str | None) -> str:
    """One Content-Security-Policy report as a line: the directive and what it
    blocked."""
    try:
        report = json.loads(body or "{}").get("csp-report", {})
    except ValueError:
        return "a report that could not be read"
    directive = report.get("effective-directive") or report.get(
        "violated-directive", "?")
    return f"{directive} blocked {report.get('blocked-uri') or '?'}"


class Walk:
    """A browser page on one screen, and the steps taken with it."""

    def __init__(self, page: Any, profile: Profile, out: Path,
                 steps: list[Step]) -> None:
        self.page = page
        self.profile = profile
        self.out = out
        self.steps = steps
        self._console: list[str] = []
        self._csp: list[str] = []
        page.add_init_script(_SHIFT_WATCH)
        page.on("console", lambda message: (
            self._console.append(message.text[:300])
            if message.type == "error" else None))
        page.on("pageerror", lambda error: self._console.append(str(error)[:300]))
        page.on("request", lambda request: (
            self._csp.append(csp_said(request.post_data))
            if request.url.endswith("/csp-report") else None))
        page.route("https://cdn.jsdelivr.net/**", self._from_disk)

    @staticmethod
    def _from_disk(route: Any) -> None:
        path = vendored(route.request.url)
        if path is None:
            # Not vendored: the network, rather than an unstyled page measured as
            # if it were the product.
            route.continue_()
        else:
            route.fulfill(path=str(path))

    def goto(self, url: str) -> bool:
        """Open ``url``; whether it answered with a page."""
        try:
            response = self.page.goto(url, wait_until="load")
        except Exception as error:  # a walk records, whatever a page does
            self._console.append(f"navigation failed: {error}"[:300])
            return False
        return response is None or response.status < 400

    def step(self, name: str, note: str = "") -> Step:
        """Record where the page stands: a screenshot, what the browser said since
        the last step, and every fact that does not hold."""
        page = self.page
        page.wait_for_timeout(250)
        step = Step(profile=self.profile.name, name=name, url=page.url, note=note)
        for fact, (_holds, script) in FACTS.items():
            try:
                found = page.evaluate(script)
            except Exception as error:
                found = [f"the fact could not be measured: {error}"[:200]]
            if found:
                step.findings[fact] = [str(one) for one in found][:12]
        try:
            shift = float(page.evaluate(
                "() => { const s = window.__lsWalkShift || 0;"
                " window.__lsWalkShift = 0; return s; }"))
        except Exception:
            shift = 0.0
        if shift > SHIFT_LIMIT:
            step.findings["layout-shift"] = [
                f"the layout shifted by {shift:.2f} with no input"]
        if self._console:
            step.findings["console"] = list(dict.fromkeys(self._console))[:12]
        if self._csp:
            step.findings["csp"] = list(dict.fromkeys(self._csp))[:12]
        self._console.clear()
        self._csp.clear()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:70]
        step.shot = f"{self.profile.name}--{len(self.steps):03d}-{slug}.png"
        try:
            page.screenshot(path=str(self.out / step.shot))
        except Exception as error:
            step.shot = ""
            step.note = f"{step.note} (no screenshot: {error})"[:300]
        self.steps.append(step)
        return step


def _sign_in(walk: Walk, base: str) -> None:
    page = walk.page
    walk.goto(f"{base}/login")
    walk.step("login")
    page.fill("#username", "pan")
    page.fill("#password", "12345678")
    with page.expect_navigation():
        page.click("button[type=submit]")


#: Longer than the inspection card waits for: the pointer at rest on a name for two
#: thirds of a second (``inspect.js``). On a phone, long enough to see it is not
#: offered.
_CARD_IS_DUE = 900


def _heads(walk: Walk, base: str, where: str, label: str) -> None:
    """Point at every card head's name of a page and record each: on a desk the
    inspection card comes up where the node has one, once the pointer has rested
    there; on a phone a tap on the name closes the card to one line and the card is
    not offered (ADR-0127 decision 11), and a second tap opens it again, so the page
    walks on as it was."""
    page = walk.page
    walk.goto(f"{base}{where}")
    walk.step(label)
    paths = page.eval_on_selector_all(
        ".status-card__head", "heads => heads.map(head => head.dataset.path)")
    for path in paths:
        head = page.locator(f'.status-card__head[data-path="{path}"]').first
        try:
            head.scroll_into_view_if_needed(timeout=2000)
            if walk.profile.phone:
                head.locator(".status-card__name").tap(timeout=2000)
            else:
                head.locator(".status-card__name").hover(timeout=2000)
        except Exception as error:
            walk.steps.append(Step(walk.profile.name, f"{label}: head {path}",
                                   page.url, note=f"not reached: {error}"[:200]))
            continue
        page.wait_for_timeout(_CARD_IS_DUE)
        raised = page.evaluate(
            "() => { const c = document.getElementById('inspect-card');"
            " return !!c && !c.hidden; }")
        state = head.evaluate(
            "head => head.closest('.tree-node')?.getAttribute('data-state-now')")
        walk.step(f"{label}: head {path}",
                  ("inspection card raised" if raised else "no inspection card")
                  + (f", the card {state}" if walk.profile.phone and state else ""))
        if page.url.split("?")[0].rstrip("/") != f"{base}{where}".rstrip("/"):
            # a tap that opened the node's page instead: back to the page walked
            walk.goto(f"{base}{where}")
        elif walk.profile.phone:
            if state == "closed":
                head.locator(".status-card__name").tap(timeout=2000)
                page.wait_for_timeout(100)
            page.keyboard.press("Escape")
    if not walk.profile.phone:
        page.mouse.move(2, 2)


def _folds(walk: Walk, base: str) -> None:
    page = walk.page
    walk.goto(f"{base}/series")
    walk.step("series index")
    page.evaluate("() => document.querySelectorAll('.ls-series-index details')"
                  ".forEach(fold => { fold.open = true; })")
    # the walk's own doing, and no input: not a shift of the page's
    page.wait_for_timeout(250)
    page.evaluate("() => { window.__lsWalkShift = 0; }")
    walk.step("series index: folds open")
    page.screenshot(path=str(walk.out / f"{walk.profile.name}--series-index-full.png"),
                    full_page=True)


def _series_view(walk: Walk, base: str, path: str) -> None:
    """A node's Series view, a pointer at rest on its first curve, and — with a
    mouse — a stretch dragged across it."""
    page = walk.page
    if not walk.goto(f"{base}/series{path}"):
        walk.step(f"series {path}", "the view did not answer")
        return
    walk.step(f"series {path}")
    plot = page.locator("svg.ls-curve__plot").first
    if plot.count() == 0 or walk.profile.phone:
        return
    plot.scroll_into_view_if_needed()
    box = plot.bounding_box()
    if box is None:
        return
    y = box["y"] + box["height"] * 0.5
    page.mouse.move(box["x"] + box["width"] * 0.6, y)
    walk.step(f"series {path}: pointer on a curve")
    page.mouse.move(box["x"] + box["width"] * 0.35, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.5, y, steps=4)
    page.mouse.move(box["x"] + box["width"] * 0.7, y, steps=4)
    walk.step(f"series {path}: a stretch being dragged")
    try:
        with page.expect_navigation(timeout=4000):
            page.mouse.up()
        walk.step(f"series {path}: over the dragged stretch")
    except Exception:
        page.mouse.up()
        walk.step(f"series {path}: after the drag", "the drag opened no window")


#: The pages every screen visits, beside the walks above: each a name and a path.
PAGES = (("branch page", "/status/services"), ("leaf page", "/status/services/web"),
         ("leaf history", "/history/services/web"),
         ("subject branch", "/status/ci/jobs"),
         ("subject node", "/status/ci/jobs/import"),
         ("events", "/events"), ("handled", "/handled"),
         ("system", "/system"), ("system installed", "/system/installed"),
         ("links", "/links"), ("copy", "/copy"), ("about", "/about"))

#: The demo's job name that comes and goes, and the node above it (ADR-0109).
GOES = "/ci/jobs/backfill"
ABOVE = "/ci/jobs"


def _pin_what_goes(walk: Walk, base: str, wait: Callable[[float], None]) -> bool:
    """Pin the job name that comes and goes while its node stands, through the wall's
    own editor; whether the pin was set."""
    page = walk.page
    for _ in range(40):
        walk.goto(f"{base}/status{ABOVE}")
        card = page.locator(".status-card").filter(
            has=page.locator(f'.status-card__head[data-path="{GOES}"]'))
        if card.count():
            break
        wait(3)
    else:
        walk.step("pin: the node never stood", "no pin set")
        return False
    try:
        card.first.locator('.status-card__head [data-control="pin"]').first.click(
            timeout=3000)
        page.wait_for_function(
            "document.activeElement !== null"
            " && document.activeElement.name === 'note'", timeout=3000)
        page.keyboard.type("The walk pins what comes and goes.")
        walk.step("pin: the editor open in its card")
        with page.expect_navigation(timeout=5000):
            card.first.locator(
                "form.maintenance-editor-form button[type=submit]").first.click()
        walk.step("pin: set")
        return True
    except Exception as error:
        walk.step("pin: not set", str(error)[:200])
        return False


def _gone(walk: Walk, base: str, wait: Callable[[float], None]) -> bool:
    """Wait until the node that comes and goes has left the tree: its card is no
    longer on the page of the node above it. Its own address is no witness — a
    path no node stands at is answered with a page all the same."""
    for _ in range(70):
        response = walk.page.request.get(f"{base}/status{ABOVE}")
        if response.ok and f'data-path="{GOES}"' not in response.text():
            return True
        wait(3)
    return False


def _what_it_left(walk: Walk, base: str) -> None:
    """What a removed node leaves (ADR-0109): its event, its suspended pin, its
    kept readings."""
    for name, path in (("removed: events", f"/events?under={ABOVE}"),
                       ("removed: handled", "/handled"),
                       ("removed: the branch it left", f"/status{ABOVE}"),
                       ("removed: its own address", f"/status{GOES}"),
                       ("removed: its check's history", f"/history{ABOVE}"),
                       ("removed: its check's series", f"/series{ABOVE}")):
        walk.goto(f"{base}{path}")
        walk.step(name)


def walk_demo(browser: Any, base: str, out: Path, steps: list[Step],
              profiles: Sequence[Profile] = PROFILES,
              wait: Callable[[float], None] = time.sleep,
              chosen: Mapping[str, str] = CHOSEN_LOOKS) -> None:
    """The live demo, on every screen, in the looks ``chosen``."""
    walks: list[tuple[Any, Walk]] = []
    for profile in profiles:
        context = open_context(browser, profile, base, chosen)
        walk = Walk(context.new_page(), profile, out, steps)
        walks.append((context, walk))
        _sign_in(walk, base)
    pinned = _pin_what_goes(walks[0][1], base, wait)
    for _context, walk in walks:
        _heads(walk, base, "/status", "wall")
        _heads(walk, base, "/status/ci", "branch wall")
        for name, path in PAGES:
            walk.goto(f"{base}{path}")
            walk.step(name)
        _folds(walk, base)
        _series_view(walk, base, "/services/web")
        _series_view(walk, base, ABOVE)
    if pinned and _gone(walks[0][1], base, wait):
        for _context, walk in walks:
            _what_it_left(walk, base)
    else:
        steps.append(Step(walks[0][1].profile.name, "removed: not seen", base,
                          note="the node did not leave while it was pinned"))
    for context, _walk in walks:
        context.close()


def walk_fixtures(browser: Any, pages: Sequence[Path], out: Path, steps: list[Step],
                  profiles: Sequence[Profile] = (PROFILES[0], PROFILES[-1])) -> None:
    """Every page of the fixture sheet, on the widest screen and on the phone."""
    for profile in profiles:
        context = browser.new_context(**profile.context())
        walk = Walk(context.new_page(), profile, out, steps)
        for path in pages:
            walk.goto(path.as_uri())
            walk.step(f"fixture {path.stem}")
        context.close()


def render_fixtures(out: Path) -> list[Path]:
    """The fixture sheet (Mode 1), rendered by its own script in a process of its
    own — it borrows the application's engine for a render, and the demo's is
    running in this one."""
    target = out / "fixtures"
    subprocess.run([sys.executable, str(_HERE / "render_ui_fixtures.py"),
                    "--out", str(target)], check=True, cwd=_REPO_ROOT,
                   stdout=subprocess.DEVNULL)
    return sorted(path for path in target.glob("*.html") if path.name != "index.html")


def start_demo(state: Path, offset: str = "36s") -> tuple[Any, str]:
    """The live demo on a port of its own, its engine running; the server and its
    address. ``offset`` starts every scenario that far in, where the build has
    failed, so the wall the walk meets is not all green."""
    os.environ["LITTLE_SISTER_DEMO_DIR"] = str(state)
    os.environ.setdefault("LITTLE_SISTER_DEMO_OFFSET", offset)
    sys.path.insert(0, str(_REPO_ROOT))
    import importlib
    importlib.import_module("tests.demo_wsgi")
    from werkzeug.serving import make_server

    from little_sister.app import app, start
    start()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@contextlib.contextmanager
def demo(offset: str = "36s") -> Iterator[str]:
    """The live demo as :func:`start_demo` starts it, in a directory of its own for as
    long as the walk takes; its address. Once a process: the application starts and
    stops once. The demo runs in that directory (``tests/demo_wsgi.py``), and its
    instance keeps its state and its lease there, so on the way out the server stops,
    then the instance — its one save, its lease let go — and the process goes back
    where it was, all before the directory goes. Left to the stop at exit, the
    instance found its lease gone with the directory and logged that it no longer
    saved, and the process stood in a directory that was no more."""
    here = Path.cwd()
    with tempfile.TemporaryDirectory() as state:
        server, base = start_demo(Path(state), offset)
        try:
            yield base
        finally:
            server.shutdown()
            from little_sister.app import stop
            stop(trigger="the walk's end")
            os.chdir(here)


def facts_counted(steps: Sequence[Step]) -> dict[str, int]:
    """How many steps each fact marked, the most marking first."""
    counted: dict[str, int] = {}
    for step in steps:
        for fact in step.findings:
            counted[fact] = counted.get(fact, 0) + 1
    return dict(sorted(counted.items(), key=lambda item: (-item[1], item[0])))


#: What the facts measured outside the document hold a step to.
_OTHER_FACTS = {
    "layout-shift": f"A step shifts the layout by no more than {SHIFT_LIMIT} "
                    "with no input — a refresh that swapped in other readings "
                    "counts, so look at the step before believing it.",
    "console": "The console reports no error.",
    "csp": "The page sends no Content-Security-Policy report.",
}


def _rows(steps: Sequence[Step]) -> Iterator[str]:
    for step in steps:
        found = "".join(
            f"<li><strong>{html.escape(fact)}</strong><ul>"
            + "".join(f"<li>{html.escape(one)}</li>" for one in places)
            + "</ul></li>" for fact, places in step.findings.items())
        shot = (f'<a href="{html.escape(step.shot)}"><img loading="lazy" '
                f'src="{html.escape(step.shot)}" alt=""></a>' if step.shot else "")
        yield (f'<article class="{"marked" if step.marked else "held"}">{shot}<div>'
               f"<h3>{html.escape(step.name)}</h3>"
               f'<p class="where">{html.escape(step.profile)} · '
               f"{html.escape(step.url)}</p>"
               + (f"<p>{html.escape(step.note)}</p>" if step.note else "")
               + (f"<ul>{found}</ul>" if found else "") + "</div></article>")


def gallery(steps: Sequence[Step]) -> str:
    """The walk as one page: what each fact holds a step to and how many it marked,
    then the marked steps, then every step in the order it was taken."""
    marked = [step for step in steps if step.marked]
    counted = facts_counted(steps)
    holds = {name: said for name, (said, _script) in FACTS.items()} | _OTHER_FACTS
    facts = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(said)}</td>"
        f"<td>{counted.get(name, 0)}</td></tr>" for name, said in holds.items())
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<title>little sister — the walk</title><style>"
        "body{font:14px/1.45 system-ui,sans-serif;margin:1.5rem;color:#222}"
        "table{border-collapse:collapse;margin-bottom:1.5rem}"
        "td,th{border:1px solid #ccc;padding:.25rem .6rem;text-align:left}"
        "article{display:flex;gap:1rem;border-top:1px solid #ddd;padding:.75rem 0}"
        "article.marked{border-left:4px solid #b3261e;padding-left:.75rem}"
        "img{width:320px;border:1px solid #ccc}h3{margin:0;font-size:1rem}"
        ".where{color:#666;margin:.1rem 0 .4rem}ul{margin:.2rem 0;padding-left:1.2rem}"
        "</style></head><body><h1>The walk</h1>"
        f"<p>{len(steps)} steps, {len(marked)} marked.</p>"
        "<table><tr><th>Fact</th><th>What it holds a step to</th>"
        f"<th>Steps marked</th></tr>{facts}</table>"
        f"<h2>Marked</h2>{''.join(_rows(marked)) or '<p>None.</p>'}"
        f"<h2>Every step</h2>{''.join(_rows(steps))}</body></html>")


def write(steps: Sequence[Step], out: Path) -> Path:
    """The gallery and the same steps as data, beside the screenshots."""
    (out / "walk.json").write_text(
        json.dumps([asdict(step) for step in steps], indent=1), encoding="utf-8")
    index = out / "index.html"
    index.write_text(gallery(steps), encoding="utf-8")
    return index


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--no-fixtures", action="store_true",
                        help="walk the live demo alone")
    parser.add_argument("--look", action="append", default=[], metavar="KEY=VALUE",
                        help="walk the live demo in another look as well as the "
                             "walk's own, e.g. boxes=packed; the fixture sheet keeps "
                             "the library's")
    args = parser.parse_args(argv)
    chosen = chosen_looks(args.look)
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright

    steps: list[Step] = []
    pages = [] if args.no_fixtures else render_fixtures(out)
    with demo() as base:
        try:
            with sync_playwright() as play:
                browser = play.chromium.launch(executable_path=(
                    str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file() else None))
                # the demo's checks run every few seconds: let each have read once,
                # and the kept series have something to draw
                time.sleep(20)
                walk_demo(browser, base, out, steps, chosen=chosen)
                walk_fixtures(browser, pages, out, steps)
                browser.close()
        finally:
            index = write(steps, out)
    marked = sum(1 for step in steps if step.marked)
    print(f"{len(steps)} steps, {marked} marked: {index}")
    for fact, count in facts_counted(steps).items():
        print(f"  {fact}: {count}")
    # Nothing fails: a review collects.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
