"""The look `boxes` on the server (ADR-0138): under `packed` the page publishes the plan
priced for packing, every level priced as it is packed and the plan the one that packs
the page shortest; under `rows`, the library's, the plan ADR-0056 prices. The browser
half — the packing itself — is ``tests/test_boxes_browser.py``'s."""

import json
import re
from unittest import TestCase

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

_BREAKPOINTS = re.compile(r"data-layout-breakpoints='([^']*)'")


def _towered() -> StatusTree:
    """Five cards of one line and a sixth of six boxes, each three leaves deep: at
    three tracks rows' plan leaves the tall card one, its row having no track to
    spare, where packed it takes all three beneath the five."""
    tree = StatusTree()
    for index in range(5):
        tree.upsert(f"/s{index}", StatusCode.OK)
    for child in range(6):
        for leaf in range(3):
            tree.upsert(f"/tall/c{child}/l{leaf}", StatusCode.OK)
    return tree


def _band(breakpoints: list[list[object]], tenths: int) -> list[object]:
    band: list[object] = []
    for start, tracks, plan in breakpoints:
        assert isinstance(start, int)
        if start > tenths:
            break
        band = [tracks, plan]
    return band


class BoxesPlanTests(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.saved = app_module.status_tree
        app_module.status_tree = _towered()
        self.addCleanup(setattr, app_module, "status_tree", self.saved)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _breakpoints(self, boxes: str) -> list[list[object]]:
        self.client.set_cookie("ls_prefs", f"boxes={boxes}")
        page = self.client.get("/status").get_data(as_text=True)
        found = _BREAKPOINTS.search(page)
        assert found is not None, "the wall publishes its plan"
        breakpoints: list[list[object]] = json.loads(found.group(1))
        return breakpoints

    def test_packed_the_tall_card_takes_the_tracks_that_pack_the_page_shortest(
            self) -> None:
        # at 1,360 pixels, three tracks: in rows every card one, packed the tall card
        # all three
        self.assertEqual(_band(self._breakpoints("rows"), 13600), [0, [1] * 6])
        self.assertEqual(_band(self._breakpoints("packed"), 13600),
                         [3, [1, 1, 1, 1, 1, 3]])

    def test_the_fragment_a_refresh_brings_carries_the_looks_own_plan(self) -> None:
        # the refresh swaps the grid with its plan: the plan of the look in force
        self.client.set_cookie("ls_prefs", "boxes=packed")
        page = self.client.get("/status").get_data(as_text=True)
        fragment = self.client.get("/status?fragment=1").get_data(as_text=True)
        drawn = _BREAKPOINTS.search(page)
        swapped = _BREAKPOINTS.search(fragment)
        assert drawn is not None and swapped is not None
        self.assertEqual(drawn.group(1), swapped.group(1))
