"""What the wall costs a browser on the anonymized tree — today's numbers the baseline.

Backlog #91 grows the wall into a tree, and before it grows the note's §7.1 step 4
takes today's cost on the deployment's own tree of §3.9, its names replaced
(``tests/anonymized_tree.py``): how many screens the wall and a node's pages are, as
the round measured them on the prototype, and how long the browser takes to swap the
ten-second refresh in. The numbers here are the baseline each stage states its growth
against, and no stage leaves a wall taller than the one before it.

**Screens** are the prototype's unit (§3.9): a page's height over 900 pixels on a desk
and 780 on a phone, the window as tall, so a page shorter than the window counts one
screen. The wall is measured at 1,280 and 1,920 pixels and on a phone, a node's page
at 1,024 as the prototype's boards were, and a card and a nested box on the wall at
the width the planner gives them, where the prototype drew a team's card alone at 700
pixels; so a card's reading is near the note's, not the same. The prototype copied
today's look by hand, and its heads carried no observation time and no next update;
its readings stand beside each measurement as what the round worked from.

**The deployed wall** is read too (backlog #91's note, §2, 2026-10-17): the recorded
tree as the deployment that runs mounts it, one team's five checks at the root, each a
card — the wall it is mostly looked at on, and on a desk 2,560 pixels wide, a screen
there 1,300 pixels tall; and at 1,920, at 1,280 and on a phone beside it. So is **the
hosts wall** (``tests/hosts_tree.py``; the note's §7.5, 2026-10-21), a second
deployment's, nine hosts the library's own types write: the wall the host types are
measured on when they declare how their levels start.

**The swap** is what the refresh costs the browser today: from the fragment's last
byte to the second frame after ``poll.js`` has put it in the page — the parse, the
observers of ``dashboard-layout.js``, ``inspect.js`` and ``maintenance.js`` that a
swap wakes (§7.10), and the layout — with the CPU throttled four times, a mid-range
phone's. Stage 2 applies the tab's map in that same span.

Each page is read in the library's theme, as a browser that never chose draws it —
cyberpunk since 2026-10-18, in a monospace face. Type comes from the machine's own
fonts, so a reading on another system differs in its wrapping, not in what stands
where; the tolerance is for that, not for growth, and a stage that grows a wall raises
the number here and says so.

Served by a real server to headless Chromium. Skipped wherever Playwright or a
Chromium binary is unavailable, so the ordinary gate does not grow a browser
dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.tree import StatusTree
from tests import anonymized_tree, hosts_tree
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4), where there is a copy; the CDN otherwise.
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: One screen: the prototype's 900 pixels on a desk and 780 on a phone (§3.9).
_DESK_SCREEN = 900
_PHONE_SCREEN = 780
#: The desk the deployment's own wall is mostly looked at on (backlog #91's note, §2): a
#: screen 2,560 pixels wide and 1,440 tall, about 1,300 of them the page's beneath the
#: browser's bars — a screen of its own.
_WIDE_DESK = 2560
_WIDE_DESK_SCREEN = 1300
_PHONE = {
    "viewport": {"width": 390, "height": _PHONE_SCREEN},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"),
}


def _screen(width: int) -> int:
    """A screen at ``width``, the window as tall: a phone's, the wide desk's or a
    desk's."""
    if width == 390:
        return _PHONE_SCREEN
    return _WIDE_DESK_SCREEN if width == _WIDE_DESK else _DESK_SCREEN


#: A reading may differ from its baseline by this much before the test speaks: the
#: wrapping another machine's fonts give, never a stage's growth.
_SCREENS_TOLERANCE = 0.15
_SCREENS_FLOOR = 0.3

#: The CPU throttled four times, Chrome's mid-tier phone.
_CPU_SLOWDOWN = 4
#: What the swap may take under it, in seconds. Before stage 3 the reading in the
#: cloud container was 0.19 s (0.04 s unthrottled). Stage 3's first slice, which
#: draws both faces of every node (five times the elements, `test_wall_cost.py`),
#: reads 0.55 to 0.62 s: a third parsing the fragment, a third `tree.js` applying
#: the map — the one layout its measure of the lines forces — and a third the
#: paint. The head's row, which read every row after each swap, and before the
#: planner had spanned the cards, took it to 0.8 to 1.0 s on 2026-10-16; reading
#: again only the rows that changed, each at its card's planned width, to 0.6 to
#: 0.7 s the same day, most of what is left the first layout of the new fragment.
#: The ceiling leaves a slower machine its room, and a stage that doubled the swap
#: again would hit it.
_SWAP_CEILING_S = 1.2


@dataclass(frozen=True)
class Case:
    """One reading of §3.9's screens tables as the real wall gives it."""

    what: str
    variant: str
    url: str
    width: int
    #: Today's reading, in screens: the baseline (one decimal, as the note has it).
    baseline: float
    #: What the prototype's hand copy of today's look read, where the round took one.
    prototype: float | None = None
    #: A card or a nested box on the wall, by its head's path, rather than the page.
    box: str = ""
    #: Read as a viewer rather than an admin: no ‖ on any head.
    viewer: bool = False


#: §3.9's Today column measured again on the real wall — the whole wall, a team's
#: card and its github box, a node's pages, each tree made worse as the prototype
#: made it — and the wall at 1,920 pixels, which the round did not draw.
#:
#: **The phone's two readings were re-stated with the head's row** (ADR-0127
#: decision 3): before stage 3 the recorded wall read 8.7 screens on a phone and the
#: blackout 27.1; the tree's first slice took them to 10.0 and 30.0, within the
#: tolerance, and the head's row to 10.4 and 31.6 — the icons end the first row now
#: and never wrap beneath it, so a name a phone's box cannot hold beside them gives
#: way last and wraps, where the icons used to take the line beneath instead — and,
#: on 2026-10-16, a name that breaks anyway carries the state on its
#: second line, beneath the icons, instead of a third line of its own: 10.1 and
#: 30.6; and the same day the caret left every head, its room the
#: name's: 10.0 and 29.9, and every desk's wall a little shorter, none taller. Those
#: readings are an admin's (the fixtures' `pan` is one), whose ‖ stands on every open
#: head without a pin; that one more square is most of what is left over the first
#: slice. A desk is wide enough for the row, and its readings stand.
#:
#: **A viewer's walls are read too**, from stage 4 (backlog #91's note, §7.5): the
#: same sign-in, its session saying it is no admin, ‖ on no head — what a team sees,
#: and the measure of which of a head's costs is an admin's alone. Beside the
#: admin's on 183b37e, in pixels: the recorded wall at a desk 4,200 to 4,241, on a
#: phone 7,779 to 8,027, at 1,920 pixels 2,736 to 2,757, and the walls whose leaves
#: all fail 10,658 to 10,702, 22,695 to 23,336 and 8,591 to 8,632.
#:
#: **The chip runs line up in columns** (ADR-0127 decision 12), the look `chip_runs:
#: aligned`, the library's own, taken knowing it costs room (backlog #91's
#: note, §2, 2026-10-15): each chip stretched to its level's column, one to a row
#: where a box had room for one, until such a run came to wrap as it comes (below).
#: The readings it raised, in pixels before and after:
#: the recorded wall at a desk 3,915 and 4,241, the same with a hundred repositories
#: as much, a team's github box 1,131 and 1,248, a team's card in an outage 6,401
#: and 6,448 and its github box 6,204 and 6,234, the card with a hundred repositories
#: 2,188 and 2,650, a check's page 1,845 and 1,874, the workflow runs' page 1,631 and
#: 1,742 and with a hundred repositories 6,835 and 7,850, the phone's wall 7,772 and
#: 7,999, and the wall at 1,920 pixels 2,432 and 2,757. A team's page read 1,949 and
#: reads 1,929; every wall whose leaves all fail, their boxes open, and the findings
#: pages read as they did.
#:
#: **A run with room for one column only wraps as it comes** (ADR-0127 decision 12;
#: backlog #91's note, §2, 2026-10-17), each chip at its own width, sharing lines, the
#: column deciding as the browser draws it. The readings it took down, in pixels
#: before and after: the recorded wall at a desk 4,241 and 3,810, the same with a
#: hundred repositories as much, on a phone 8,027 and 7,480, at 1,920 pixels 2,757
#: and 2,354; a team's github box 1,248 and 1,104, its card in an outage 6,448 and
#: 6,420, the card with a hundred repositories 2,650 and 2,161, and the workflow
#: runs' page with a hundred 7,874 and 7,850; a viewer's walls at a desk 4,200 and
#: 3,768, on a phone 7,779 and 7,232 and at 1,920 pixels 2,736 and 2,333. Every wall
#: whose leaves all fail, their boxes open, and every other page read as they did.
#: The walls are shorter now than with every run wrapped — at a desk 3,915, on a
#: phone 7,772, at 1,920 pixels 2,432 — and a page whose wide levels hold many
#: columns is not: a hundred repositories' 6,859 wrapped.
#:
#: **The deployed wall** (backlog #91's note, §2, 2026-10-17): alpha's five checks at
#: the root, each a card, as the deployment that runs mounts them, read where it is
#: mostly looked at — 2,560 pixels, a screen there 1,300 tall — and at 1,920, at
#: 1,280 and on a phone. Its first readings, an admin's, in pixels: 1,640 at 2,560
#: and a viewer's 1,619, 1,619 at 1,920, 1,832 at 1,280 and 3,405 on a phone. At
#: 2,560 the planner gives github three of the seven tracks, 951 pixels tall, and
#: aws one, its three accounts beneath each other, 1,447: the wall's height.
#:
#: **The library's theme became cyberpunk** on 2026-10-18, which a
#: browser that never chose draws in, so every reading here is cyberpunk's: its
#: monospace face reads the walls taller than the plain theme's proportional one did.
#: In pixels, plain and cyberpunk: the recorded wall at a desk 3,810 and 4,036, on a
#: phone 7,480 and 8,262, at 1,920 pixels 2,354 and 2,667; every leaf failing 10,702
#: and 11,701, 23,336 and 25,868, 8,632 and 9,403; a viewer's walls 3,768 and 3,947,
#: 7,232 and 8,014, 2,333 and 2,622; a team's card in an outage 6,420 and 6,982; the
#: workflow runs' page with a hundred repositories 7,850 and 7,960; the 300 findings'
#: page 31,150 and 37,576; and the deployed wall at 2,560 pixels 1,640 and 1,703, at
#: 1,920 1,619 and 1,703, at 1,280 1,832 and 1,849 and on a phone 3,405 and 3,651 —
#: its aws card 1,447 and 1,511, its github card 951 and 1,056.
#: **The hosts wall** (2026-10-21), read in the library's theme as it was drawn: one
#: screen at 2,560 pixels, its hosts' card 646 tall beside the family's 889; at 1,920
#: pixels 1,081, at 1,280 992 and on a phone 2,476, a viewer's 2,434. The same day the
#: library's host types came to propose how their levels first look (the note's §7.5,
#: the third slice), drawn here as they propose it, and the wall reads as it did but
#: at 1,280 pixels, 1,059: priced as the chips they are drawn as, a host's leaves no
#: longer make its card the taller in the planner's rows, which gives each card one of
#: two tracks where it gave the hosts two of three — 67 pixels more, until the flip.
#: Later the same day each leaf of the Mac's node, which ``host-metrics`` and
#: ``macos-memory`` share, starts as its own check proposes: the Mac's watched processes
#: a chip where their branch stood open, every host's leaves priced as the chips they
#: are drawn as. The wall reads as it did at 2,560 and 1,920 pixels, at 1,280 986 — each
#: card one of two tracks still, the hosts' 794 tall — and on a phone 2,382, a viewer's
#: 2,361.
#: **An open head's buttons stand where the look ``head_buttons`` puts them**
#: (2026-10-21, ADR-0127 decision 3), read here in the library's, ``pointer``:
#: right after the name, the state outside them. No wall stands taller, and some
#: stand shorter, the state no longer between two of the toolbar's gaps — a coarse
#: pointer's are 8 pixels — but 0.4em after the title. In pixels before and after: the
#: recorded wall on a phone 8,262 and 8,199, every leaf failing 25,868 and 25,702 and
#: a viewer's 24,670 and 24,504, the deployed wall on a phone 3,651 and 3,610 and its
#: github card at 2,560 pixels 1,056 and 1,035, and the hosts wall on a phone, a
#: viewer's, 2,361 and 2,340. Under ``line`` every wall but the hosts wall at 2,560
#: pixels stands taller, a line of buttons on every open head — the recorded wall at a
#: desk 4,830, on a phone 9,323 — and under ``name`` none, ↗ out of the row: 3,947
#: and 8,014.
#: **A branch says why it has its color** (ADR-0135 decision 7, 2026-10-24): a card of
#: its own right after Time wherever a branch fails or holds something handled, each
#: of its lists five rows open and the rest folded beneath *N more*. The node pages it
#: stands on read taller by it, in pixels without it and with it: a team's page 2,182
#: and 2,422, its four failing parts listed; a check's page 2,027 and 2,190; the
#: workflow runs' page 1,766 and 1,903, with a hundred repositories 7,960 and 8,203,
#: and in an outage 3,950 and 4,217, where its list unfolded read 5,723. Every wall
#: reads as it did, and so does every page with no branch at its head.
#: **The interactive wall's flip** (backlog #91's note, §7.5, 2026-10-25): a level
#: nobody speaks for starts open, its healthy shown, and one that would draw more than
#: thirty boxes as chips; *+N more* went with today's density. Since then each tree is
#: drawn with what the family's packages that come out with the flip propose for their
#: levels, stated by path (``tests/family_looks.py``), since no deployment of theirs
#: draws the wall without them. The two read, in pixels before and after: the recorded
#: wall at a desk 4,036 and 3,358, on a phone 8,199 and 8,280 and at 1,920 pixels
#: 2,667 and 2,318, a viewer's 3,947 and 3,289, 8,014 and 8,088 and 2,622 and 2,318;
#: every leaf failing 11,701 and 3,331, 25,702 and 7,975 and 9,403 and 2,390, a
#: viewer's 11,199 and 3,248, 24,504 and 7,744 and 9,028 and 2,390 — three failures
#: open in each card, where every failing leaf stood open; the wall with a hundred
#: repositories 4,036 and 3,975; a team's github box 1,183 and 1,273, in an outage
#: 6,768 and 1,402; its card in an outage 6,982 and 3,207, and with a hundred
#: repositories 2,223 and 3,783, every repository a chip where three boxes stood before
#: *+97 more*; a check's page 2,190 and 2,174, the workflow runs' page in an outage
#: 4,217 and 3,758; wiz's page 1,548 and 900, informational's own page 2,451 and 900
#: and with 300 findings 37,576 and 900, its healthy findings folded; the deployed wall
#: at 2,560 pixels 1,703 and 1,328, a viewer's 1,703 and 1,307, its aws card 1,511
#: and 1,137 and its github card 1,035 and 1,066, at 1,280 1,849 and 1,741 and on a
#: phone 3,610 and 3,618; and the hosts wall at 2,560 pixels 1,300 and 1,367, a
#: viewer's 1,300 and 1,346, at 1,920 1,081 and 1,195, at 1,280 986 and 1,415 and on a
#: phone 2,382 and 3,379, a viewer's 2,340 and 3,310, its seven local hosts each a box
#: where four waited behind *+4 more*. Drawn with the same declarations on today's
#: look, the slice before the flip read the recorded wall at 3,167, 7,803 and 2,227, a
#: viewer's at 3,098, 7,680 and 2,227, a team's github box 1,211 and its card in an
#: outage 3,016, the deployed wall on a phone 3,535 and its github card 1,137, and the
#: hosts wall 1,300, 900, 986 and 2,382: what the flip itself opens is the quiet leaves
#: nobody speaks for — github's flat aspects, its rate limit and the load test — and
#: every box *+N more* held back. Every other page reads as it did.
CASES: tuple[Case, ...] = (
    Case("the whole wall, desk", "recorded", "/status", 1280, 3.7, 4.0),
    Case("the whole wall, every leaf failing, desk", "blackout", "/status", 1280,
         3.7, 12.0),
    Case("the whole wall, alpha with 100 repositories, desk", "wide", "/status",
         1280, 4.4),
    Case("a team's github box, one failure", "recorded", "/status", 1280, 1.4, 1.1,
         box="/alpha/github"),
    Case("a team's card, an outage", "outage", "/status", 1280, 3.6, 8.4,
         box="/alpha"),
    Case("a team's github box, an outage", "outage", "/status", 1280, 1.6, 6.6,
         box="/alpha/github"),
    Case("a team's card with 100 repositories", "wide", "/status", 1280, 4.2, 3.6,
         box="/alpha"),
    Case("a team's page", "recorded", "/status/alpha", 1024, 2.7, 2.2),
    Case("a check's page (github)", "recorded", "/status/alpha/github", 1024, 2.4,
         1.3),
    Case("a wide branch's page (20 repositories)", "recorded",
         "/status/alpha/github/actions", 1024, 2.1, 1.7),
    Case("the same with 100 repositories", "wide", "/status/alpha/github/actions",
         1024, 9.1, 7.8),
    Case("an outage: the workflow runs' page", "outage",
         "/status/alpha/github/actions", 1024, 4.2, 4.2),
    Case("wiz's page, informational open", "recorded", "/status/alpha/wiz", 1024,
         1.0, 1.1),
    Case("informational's own page, 17 findings", "recorded",
         "/status/alpha/wiz/informational", 1024, 1.0, 1.4),
    Case("informational's own page, 300 findings", "findings",
         "/status/alpha/wiz/informational", 1024, 1.0, 20.0),
    Case("the whole wall, phone", "recorded", "/status", 390, 10.6, 8.6),
    Case("the whole wall, every leaf failing, phone", "blackout", "/status", 390,
         10.2, 28.7),
    Case("the whole wall, 1,920 pixels", "recorded", "/status", 1920, 2.6),
    Case("the whole wall, every leaf failing, 1,920 pixels", "blackout", "/status",
         1920, 2.7),
    Case("the whole wall, desk, a viewer", "recorded", "/status", 1280, 3.7,
         viewer=True),
    Case("the whole wall, every leaf failing, desk, a viewer", "blackout", "/status",
         1280, 3.6, viewer=True),
    Case("the whole wall, phone, a viewer", "recorded", "/status", 390, 10.4,
         viewer=True),
    Case("the whole wall, every leaf failing, phone, a viewer", "blackout",
         "/status", 390, 9.9, viewer=True),
    Case("the whole wall, 1,920 pixels, a viewer", "recorded", "/status", 1920, 2.6,
         viewer=True),
    Case("the whole wall, every leaf failing, 1,920 pixels, a viewer", "blackout",
         "/status", 1920, 2.7, viewer=True),
    Case("the deployed wall, 2,560 pixels", "deployed", "/status", _WIDE_DESK, 1.0),
    Case("the deployed wall, 2,560 pixels, a viewer", "deployed", "/status",
         _WIDE_DESK, 1.0, viewer=True),
    Case("the deployed wall's aws card, 2,560 pixels", "deployed", "/status",
         _WIDE_DESK, 0.9, box="/aws"),
    Case("the deployed wall's github card, 2,560 pixels", "deployed", "/status",
         _WIDE_DESK, 0.8, box="/github"),
    Case("the deployed wall, 1,920 pixels", "deployed", "/status", 1920, 1.9),
    Case("the deployed wall, desk", "deployed", "/status", 1280, 1.9),
    Case("the deployed wall, phone", "deployed", "/status", 390, 4.6),
    Case("the hosts wall, 2,560 pixels", hosts_tree.VARIANT, "/status", _WIDE_DESK,
         1.1),
    Case("the hosts wall, 2,560 pixels, a viewer", hosts_tree.VARIANT, "/status",
         _WIDE_DESK, 1.0, viewer=True),
    Case("the hosts wall, 1,920 pixels", hosts_tree.VARIANT, "/status", 1920, 1.3),
    Case("the hosts wall, desk", hosts_tree.VARIANT, "/status", 1280, 1.6),
    Case("the hosts wall, phone", hosts_tree.VARIANT, "/status", 390, 4.3),
    Case("the hosts wall, phone, a viewer", hosts_tree.VARIANT, "/status", 390, 4.2,
         viewer=True),
)

#: The page's height once its layout has settled: the scripts have planned the grid
#: and the fonts are in, and two frames read the same.
_HEIGHT = """
    async () => {
      await document.fonts.ready;
      const frame = () => new Promise(r => requestAnimationFrame(() => r()));
      const read = () => document.documentElement.scrollHeight;
      let last = -1;
      for (let i = 0; i < 20; i += 1) {
        await frame(); await frame();
        const now = read();
        if (now === last) { return now; }
        last = now;
      }
      return last;
    }
"""

#: A card's or a box's height on the wall, by the path its head carries.
_BOX_HEIGHT = """
    path => {
      const head = document.querySelector(
          '.status-card__head[data-path="' + path + '"], ' +
          '.status-node__self[data-path="' + path + '"]');
      if (!head) { return null; }
      const box = head.closest('.status-card, .status-node');
      return {height: box.getBoundingClientRect().height,
              width: box.getBoundingClientRect().width};
    }
"""

#: One refresh, timed: `poll.js` is asked for it as a tab coming back is, and the
#: fragment's arrival, the swap and the second frame after it are read off the
#: clock; nothing swapped within ten seconds answers null.
_SWAP = """
    () => new Promise(resolve => {
      const grid = document.getElementById('status-grid');
      const seen = performance.getEntriesByType('resource').length;
      const patience = setTimeout(() => { observer.disconnect(); resolve(null); },
                                  10000);
      const observer = new MutationObserver(() => {
        observer.disconnect();
        clearTimeout(patience);
        const swapped = performance.now();
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const painted = performance.now();
          const fragment = performance.getEntriesByType('resource').slice(seen)
              .filter(e => e.name.indexOf('fragment=1') >= 0).pop();
          resolve({arrived: fragment ? fragment.responseEnd : null,
                   requested: fragment ? fragment.startTime : null,
                   swapped: swapped, painted: painted});
        }));
      });
      observer.observe(grid, {childList: true});
      document.dispatchEvent(new Event('visibilitychange'));
    })
"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class WallCostTests(unittest.TestCase):
    """The screens of §3.9 on the real wall, and the swap's time."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""
    trees: ClassVar[dict[str, StatusTree]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None))
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error
        cls.trees = {variant: anonymized_tree.build(variant)
                     for variant in anonymized_tree.VARIANTS}
        cls.trees[hosts_tree.VARIANT] = hosts_tree.build()
        cls.saved_tree = app_module.status_tree
        cls.saved_config = app_module.config
        cls.saved_error = app_module.engine_error
        cls.saved_looks = app_module.first_looks
        app_module.status_tree = cls.trees["recorded"]
        # a deployment's pages carry no banner about an engine never started
        app_module.engine_error = None
        # the deployment's line budget (§3.9); depth at its default
        app_module.config = replace(app_module.config,
                                    reason_cap=anonymized_tree.REASON_CAP)
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree = cls.saved_tree
        app_module.config = cls.saved_config
        app_module.engine_error = cls.saved_error
        app_module.first_looks = cls.saved_looks
        cls.browser.close()
        cls.playwright.stop()

    @staticmethod
    def _vendored(route: Any) -> None:
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _signed_in(self, width: int, *, viewer: bool = False) -> Any:
        """A page signed in as the fixtures' `pan` — an admin, so ‖ stands on every
        open head without a pin, or with ``viewer`` the same session saying it is
        none — in a window of ``width``: the phone's, or a desk's one screen tall."""
        settings = (dict(_PHONE) if width == 390
                    else {"viewport": {"width": width, "height": _screen(width)}})
        context = self.browser.new_context(**settings, reduced_motion="reduce")
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        page = context.new_page()
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        if viewer:
            self._as_a_viewer(context)
        return page

    def _as_a_viewer(self, context: Any) -> None:
        """The session the sign-in opened, signed again by the application's own
        serializer with ``admin`` false: what a team's member reads, ‖ on no head.
        The fixtures' one login is an admin's, and the session is what every page
        reads the role from (``identity.session_identity``)."""
        app = app_module.app
        serializer = app.session_interface.get_signing_serializer(  # type: ignore[attr-defined]
            app)
        name = app.config["SESSION_COOKIE_NAME"]
        cookie = next(c for c in context.cookies(self.base) if c["name"] == name)
        session = dict(serializer.loads(cookie["value"]))
        session["admin"] = False
        context.add_cookies([{**cookie, "value": serializer.dumps(session)}])

    def _open(self, page: Any, case: Case) -> None:
        app_module.status_tree = self.trees[case.variant]
        # the line budget of the deployment the tree is from, and the first look its
        # types propose: the hosts tree's from the library's own host types, and the
        # family's packages' stated by path on both trees (`tests/family_looks.py`)
        app_module.config = replace(
            app_module.config,
            reason_cap=(hosts_tree.REASON_CAP if case.variant == hosts_tree.VARIANT
                        else anonymized_tree.REASON_CAP))
        app_module.first_looks = (
            hosts_tree.first_looks(self.trees[case.variant], app_module.config)
            if case.variant == hosts_tree.VARIANT
            else anonymized_tree.first_looks(self.trees[case.variant],
                                             app_module.config))
        page.goto(f"{self.base}{case.url}")
        page.wait_for_load_state("networkidle")

    def _screens(self, page: Any, case: Case) -> tuple[float, str]:
        """``case``'s reading in screens, and the pixels it was taken from."""
        screen = _screen(case.width)
        height = page.evaluate(_HEIGHT)
        if case.box:
            box = page.evaluate(_BOX_HEIGHT, case.box)
            self.assertIsNotNone(box, f"no card or box at {case.box}")
            return (box["height"] / screen,
                    f"{box['height']:.0f} px tall, {box['width']:.0f} px wide")
        return height / screen, f"{height} px"

    def test_the_screens_of_the_round_hold_on_the_real_wall(self):
        # each case loads its tree into the server and its page into a window of
        # its width; the reading is the page's height, or a card's on the wall
        pages: dict[tuple[int, bool], Any] = {}
        readings = []
        for case in CASES:
            with self.subTest(case=case.what, width=case.width):
                page = pages.get((case.width, case.viewer))
                if page is None:
                    page = pages[case.width, case.viewer] = self._signed_in(
                        case.width, viewer=case.viewer)
                self._open(page, case)
                # a viewer's heads carry no ‖, and an admin's every open one does
                pins = page.locator('.node-icons > [data-control="pin"]').count()
                self.assertEqual(pins == 0, case.viewer,
                                 f"{case.what}: {pins} pin mark(s) on the page")
                screens, pixels = self._screens(page, case)
                readings.append(f"{case.what} at {case.width}: {screens:.1f} "
                                f"screens ({pixels}); baseline {case.baseline}"
                                + (f", the prototype's {case.prototype}"
                                   if case.prototype is not None else ""))
                allowed = max(_SCREENS_FLOOR, case.baseline * _SCREENS_TOLERANCE)
                self.assertLessEqual(
                    abs(screens - case.baseline), allowed,
                    f"{case.what} at {case.width} pixels: {screens:.2f} screens "
                    f"({pixels}) against a baseline of {case.baseline}; the readings "
                    "so far:\n  " + "\n  ".join(readings))

    def test_the_window_stands_through_a_swap(self):
        # The recorded wall on a desk, scrolled down, was scrolled 24 pixels back up by
        # a refresh, and from its foot 1,347: the browser's own scroll anchoring held on
        # to a node of a layout the swap passes through, the grid not yet planned. The
        # window stands where it was
        page = self._signed_in(1280)
        self._open(page, CASES[0])
        foot = page.evaluate("document.documentElement.scrollHeight - innerHeight")
        for scrolled in (1200, foot):
            page.evaluate(f"window.scrollTo(0, {scrolled})")
            with self.subTest(scrolled=scrolled):
                self.assertIsNotNone(page.evaluate(_SWAP), "nothing was swapped")
                self.assertAlmostEqual(page.evaluate("window.scrollY"), scrolled,
                                       delta=1)

    def test_the_swap_under_a_throttled_cpu(self):
        # the recorded wall on a desk, the CPU four times slower: one refresh,
        # and what the browser took from the fragment's last byte to the second
        # frame after the swap
        page = self._signed_in(1280)
        self._open(page, CASES[0])
        page.evaluate(_HEIGHT)
        client = page.context.new_cdp_session(page)
        client.send("Emulation.setCPUThrottlingRate", {"rate": _CPU_SLOWDOWN})
        try:
            took = []
            for _ in range(3):
                clock = page.evaluate(_SWAP)
                self.assertIsNotNone(clock, "nothing was swapped in ten seconds")
                self.assertIsNotNone(clock["arrived"], "no fragment was fetched")
                took.append((clock["painted"] - clock["arrived"]) / 1000)
        finally:
            client.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        swap = sorted(took)[1]
        self.assertLessEqual(
            swap, _SWAP_CEILING_S,
            f"the swap took {swap:.3f} s with the CPU throttled {_CPU_SLOWDOWN}x "
            f"(the three: {', '.join(f'{t:.3f}' for t in took)})")
        # and the fragment is the wall's: the grid was swapped, not emptied
        self.assertGreater(
            page.locator("#status-grid .status-card").count(), 1)
