"""The declarative action list — `config/actions.yaml` (ADR-0038).

A filler the library itself ships, so the common case — a link with the node's
details in the query string — needs no deployment code at all.
"""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import slots
from little_sister.actions import (
    PLACEHOLDERS,
    Action,
    forget_actions,
    load_actions,
)
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse

JIRA = ("https://tracker.example.org/new"
        "?summary={reason}&node={path}&status={code}")


def _config(directory, body):
    """A configuration root holding just an actions aspect (and a checks dir, which
    every root is expected to be able to carry)."""
    root = Path(directory)
    (root / "checks").mkdir(parents=True, exist_ok=True)
    (root / "actions.yaml").write_text(body, encoding="utf-8")
    return root


class LoadTests(TestCase):
    def _load(self, body):
        with tempfile.TemporaryDirectory() as directory:
            return load_actions(_config(directory, body))

    def test_a_minimal_entry_loads(self):
        actions = self._load(
            "actions:\n"
            "  - label: Raise a ticket\n"
            "    slot: reason.actions\n"
            f"    url: \"{JIRA}\"\n")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].label, "Raise a ticket")
        self.assertEqual(actions[0].slot, "reason.actions")
        self.assertEqual(actions[0].under, "")

    def test_every_field_loads(self):
        actions = self._load(
            "actions:\n"
            "  - label: File\n"
            "    slot: node.actions\n"
            "    url: https://example.org/new?n={path}\n"
            "    icon: jira\n"
            "    under: /system/alpha\n")
        self.assertEqual(actions[0].icon, "jira")
        self.assertEqual(actions[0].under, "/system/alpha")

    def test_an_entry_without_a_label_or_url_is_dropped(self):
        for body in ("actions:\n  - slot: node.actions\n    url: https://x/\n",
                     "actions:\n  - label: X\n    slot: node.actions\n"):
            with self.subTest(body=body):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertEqual(self._load(body), ())

    def test_an_unknown_slot_is_dropped_and_the_known_ones_are_named(self):
        with self.assertLogs("little_sister", level="WARNING") as logs:
            actions = self._load(
                "actions:\n  - label: X\n    slot: card.buttons\n"
                "    url: https://x/\n")
        self.assertEqual(actions, ())
        self.assertIn("reason.actions", "\n".join(logs.output))

    def test_an_unknown_placeholder_is_refused_at_load(self):
        # rendered broken, it would silently send the operator somewhere useless
        with self.assertLogs("little_sister", level="WARNING") as logs:
            actions = self._load(
                "actions:\n  - label: X\n    slot: node.actions\n"
                "    url: https://x/?s={summary}\n")
        self.assertEqual(actions, ())
        self.assertIn("{summary}", "\n".join(logs.output))

    def test_one_bad_entry_never_costs_the_others(self):
        with self.assertLogs("little_sister", level="WARNING"):
            actions = self._load(
                "actions:\n"
                "  - label: Good\n    slot: node.actions\n    url: https://x/\n"
                "  - label: Bad\n    slot: nope\n    url: https://x/\n"
                "  - label: Also good\n    slot: reason.actions\n"
                "    url: https://y/\n")
        self.assertEqual([a.label for a in actions], ["Good", "Also good"])

    def test_a_file_that_is_not_a_list_is_ignored(self):
        for body in ("actions: 3\n", "just a string\n", "other: 1\n"):
            with self.subTest(body=body):
                with self.assertLogs("little_sister", level="WARNING"):
                    self.assertEqual(self._load(body), ())

    def test_an_empty_file_is_not_a_complaint(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_actions(_config(directory, "")), ())

    def test_roots_are_layered_not_merged(self):
        # a site root *adds* its actions; it does not restate the base's
        with tempfile.TemporaryDirectory() as base, \
                tempfile.TemporaryDirectory() as site:
            _config(base, "actions:\n  - label: Base\n    slot: node.actions\n"
                          "    url: https://b/\n")
            _config(site, "actions:\n  - label: Site\n    slot: node.actions\n"
                          "    url: https://s/\n")
            actions = load_actions(f"{base}:{site}")
        self.assertEqual([a.label for a in actions], ["Base", "Site"])


class TemplateTests(TestCase):
    def _action(self, url, **kw):
        return Action(label="X", url=url, slot="node.actions", **kw)

    def _href(self, url, **kw):
        return self._action(url).href(
            path=kw.get("path", "/db"), name=kw.get("name", "db"),
            code=kw.get("code", "ERROR"), reason=kw.get("reason", "first"),
            reasons=kw.get("reasons", ["first", "second"]))

    def test_every_documented_placeholder_substitutes(self):
        url = "https://x/?" + "&".join(f"{f}={{{f}}}" for f in PLACEHOLDERS)
        href = self._href(url)
        for field in PLACEHOLDERS:
            with self.subTest(field=field):
                self.assertNotIn("{" + field + "}", href)

    def test_values_are_percent_encoded(self):
        # a reason full of ampersands lands in a query string intact, and an action
        # can never be a way to get markup onto a page
        href = self._href("https://x/?s={reason}",
                          reason='a & b <script>"')
        self.assertIn("a%20%26%20b%20%3Cscript%3E%22", href)
        self.assertNotIn("<script>", href)

    def test_reasons_carries_every_line(self):
        href = self._href("https://x/?b={reasons}", reasons=["one", "two"])
        self.assertIn("one%0Atwo", href)

    def test_under_is_compared_segment_wise(self):
        action = self._action("https://x/", under="/system/alpha")
        self.assertTrue(action.applies_to("/system/alpha"))
        self.assertTrue(action.applies_to("/system/alpha/disk"))
        self.assertFalse(action.applies_to("/system/alphaville"))
        self.assertFalse(action.applies_to("/system"))

    def test_a_leading_slash_is_optional_in_under(self):
        self.assertTrue(
            self._action("https://x/", under="system").applies_to("/system/a"))

    def test_no_under_means_everywhere(self):
        self.assertTrue(self._action("https://x/").applies_to("/anything/at/all"))


class RenderTests(TestCase):
    """The library's own filler, on the pages it fills."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)

    def _configure(self, body):
        root = _config(self._directory.name, body)
        os.environ["LITTLE_SISTER_CONFIG_DIR"] = str(root)
        self.addCleanup(os.environ.pop, "LITTLE_SISTER_CONFIG_DIR", None)
        forget_actions()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _body(self, url="/status"):
        return self.client.get(url).get_data(as_text=True)

    def test_no_configuration_means_no_chips(self):
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        body = self._body()
        self.assertIn("boom", body)
        self.assertNotIn("tracker.example.org", body)

    def test_a_node_action_renders_from_configuration_alone(self):
        self._configure(
            "actions:\n  - label: File it\n    slot: node.actions\n"
            f"    url: \"{JIRA}\"\n")
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")
        body = self._body()
        self.assertIn("File it", body)
        self.assertIn('class="node-action"', body)
        self.assertIn("node=%2Fdb", body)
        self.assertIn("status=ERROR", body)
        self.assertIn("summary=connection%20refused", body)

    def test_a_reason_action_renders_per_line(self):
        self._configure(
            "actions:\n  - label: Raise\n    slot: reason.actions\n"
            "    url: https://tracker.example.org/new?s={reason}\n")
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, ["one", "two"])
        body = self._body("/status/db")
        self.assertEqual(body.count("https://tracker.example.org/new?s="), 2)
        self.assertIn("s=one", body)
        self.assertIn("s=two", body)

    def test_under_aims_an_action_at_one_subtree(self):
        self._configure(
            "actions:\n  - label: Only here\n    slot: node.actions\n"
            "    url: https://tracker.example.org/new?n={path}\n"
            "    under: /system\n")
        self._login()
        self.tree.upsert("/system/alpha", StatusCode.ERROR, "boom")
        self.tree.upsert("/other", StatusCode.ERROR, "boom")
        self.assertIn("Only here", self._body("/status/system/alpha"))
        self.assertNotIn("Only here", self._body("/status/other"))

    def test_a_node_action_can_carry_the_whole_condition(self):
        self._configure(
            "actions:\n  - label: File it\n    slot: node.actions\n"
            "    url: https://tracker.example.org/new?t={reason}&b={reasons}\n")
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, ["headline", "the detail"])
        body = self._body("/status/db")
        self.assertIn("t=headline", body)
        self.assertIn("b=headline%0Athe%20detail", body)

    def test_an_action_with_an_icon_is_a_square_and_one_without_its_label(self):
        # in a head's row an action that names an icon is a square like the head's
        # own buttons, its label its tooltip and accessible name; one that names
        # none keeps its label as a chip (ADR-0127 decision 3)
        self._configure(
            "actions:\n  - label: File it\n    slot: node.actions\n"
            "    url: https://tracker.example.org/new?n={path}\n    icon: jira\n"
            "  - label: Mute it\n    slot: node.actions\n"
            "    url: https://tracker.example.org/mute?n={path}\n"
            "  - label: Raise\n    slot: reason.actions\n"
            "    url: https://tracker.example.org/raise?s={reason}\n    icon: jira\n")
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")
        page = parse(self._body())
        rail = page.one("status-card__head").one("node-actions")
        square, chip = [a for a in rail.children if not isinstance(a, str)]
        self.assertTrue(square.has("node-action") and square.has("is-icon"))
        self.assertEqual((square.attrs.get("title"), square.attrs.get("aria-label")),
                         ("File it", "File it"))
        self.assertEqual(square.text(), "")
        icon = square.one("action-icon")
        self.assertTrue(icon.attrs.get("src"))
        # at the head's own glyphs' size, 16 of the square's 24 pixels
        self.assertEqual((icon.attrs.get("width"), icon.attrs.get("height")),
                         ("16", "16"))
        self.assertTrue(chip.has("node-action") and not chip.has("is-icon"))
        self.assertEqual(chip.text(), "Mute it")
        self.assertEqual(chip.attrs.get("title"), "Mute it — /db")
        self.assertNotIn("aria-label", chip.attrs)
        # a line's chip keeps the icon beside its label
        line = page.one("status-node__reason").one("reason-actions")
        raise_ = next(a for a in line.all("reason-action") if a.text() == "Raise")
        self.assertFalse(raise_.has("is-icon"))
        self.assertEqual(raise_.one("action-icon").attrs.get("width"), "12")

    def test_the_kiosk_renders_none(self):
        self._configure(
            "actions:\n  - label: File it\n    slot: node.actions\n"
            "    url: https://tracker.example.org/new\n")
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.assertNotIn("File it", self._body())

    def test_a_configured_chip_and_a_package_chip_share_the_rail(self):
        from tests.demo_extension import node_action
        self._configure(
            "actions:\n  - label: Configured\n    slot: node.actions\n"
            "    url: https://tracker.example.org/new\n")
        slots.register("node.actions", "tests.demo_extension",
                       "node_action.html", node_action)
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        body = self._body("/status/db")
        self.assertIn("Configured", body)
        self.assertIn('data-demo-node-action="node-filler"', body)

    def test_the_inspection_card_leaves_a_lines_and_a_heads_chips_alone(self):
        # the inspection card answers a node's name alone (`NAMES`, `inspect.js`) —
        # a chip, a head's toggle, the strip's name — and the chips of a box's lines
        # and of every head stand in the rows, outside every name: a line's Copy, a
        # configured chip on a line and a node's own. A chip is a control of its
        # own: a tap on one is a tap on it, where a card on the row once took the
        # first. The tap itself is `tests/test_actions_browser.py`'s.
        script = self.client.get("/static/js/inspect.js").get_data(as_text=True)
        found = re.search(r"var NAMES = '([^']+)';", script)
        assert found is not None
        self.assertEqual(found.group(1).split(", "),
                         [".tree-chip", '[data-control="toggle"]', ".ls-strip__name"])

        def a_name(node: Element) -> bool:
            return (node.has("tree-chip") or node.has("ls-strip__name")
                    or node.attrs.get("data-control") == "toggle")
        self._configure(
            "actions:\n  - label: File it\n    slot: node.actions\n"
            f"    url: \"{JIRA}\"\n"
            "  - label: Raise\n    slot: reason.actions\n"
            f"    url: \"{JIRA}\"\n")
        self._login()
        self.tree.upsert("/ci/reviews", StatusCode.WARN,
                         {"pr-1": "waiting 3h for a reviewer",
                          "pr-2": "waiting 5h for a reviewer"}, members=True)
        self.tree.upsert("/ci/build", StatusCode.ERROR, "the build failed on main")
        self.tree.upsert("/uplink", StatusCode.WARN, "packet loss of 2 %")
        for url in ("/status", "/status?fragment=1", "/status/ci"):
            page = parse(self._body(url))
            rows = [row for row in page.walk() if "data-path" in row.attrs]
            chips = [chip for row in rows
                     for chip in row.all("reason-action") + row.all("node-action")]
            self.assertGreater(len(chips), 0, url)
            for chip in chips:
                node = chip
                while node is not None:
                    self.assertFalse(a_name(node), (url, chip.source()[:120]))
                    node = node.parent

    def test_system_names_the_built_in_filler(self):
        self._login()
        body = self._body("/system/installed")
        self.assertIn("built-in", body)
        self.assertIn("node.actions", body)


class ChipsWhereTheyStandTests(TestCase):
    """Where the action chips stand today, held through the stages of the interactive
    wall (backlog #91, its note's §7.1 step 7): through the demo's fillers beside the
    library's Copy, as a deployment's chips come. A line's chips stand in its own rail,
    on every surface that lists the line; a node's chip in its head, on a card and on a
    nested box, and in the status line of a leaf's own page; the refresh draws the same;
    and a chip is one chip wherever it stands."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        from tests.demo_extension import action, node_action
        # registered for each test, since the suite empties the registry before every
        # one (`conftest.py`); a reset puts the library's own fillers back
        slots.register("reason.actions", "tests.demo_extension", "reason_action.html",
                       action)
        slots.register("node.actions", "tests.demo_extension", "node_action.html",
                       node_action)
        self.addCleanup(slots.forget_fillers)
        # a branch with lines of its own above a box of member lines and a box of
        # prose, and a leaf card of prose
        self.tree.upsert("/ci", StatusCode.WARN, [
            Entry("scope", "2 regions in scope", StatusCode.OK),
            Entry("unread", "eu-west-1 cannot be read", StatusCode.WARN)],
            members=True)
        self.tree.upsert("/ci/reviews", StatusCode.WARN, {
            "pr-1": "waiting 3h for a reviewer", "pr-2": "waiting 5h for a reviewer",
            "pr-3": "waiting 9h for a reviewer"}, members=True)
        self.tree.upsert("/ci/build", StatusCode.ERROR, "the build failed on main")
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")

    def _page(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def _labels(rail):
        return [chip.text() for chip in rail.all(tag="a")]

    def _line_rails(self, within, line_class):
        """Each line's actions rail, in the lines' order, with its labels."""
        rails = []
        for line in within.all(line_class):
            rail = line.one("reason-actions")
            rails.append(self._labels(rail))
        return rails

    def _row(self, page, path, row_class):
        rows = [row for row in page.all(row_class)
                if row.attrs.get("data-path") == path]
        self.assertEqual(len(rows), 1, (path, row_class))
        return rows[0]

    def _card(self, page, path):
        return next(card for card in page.all("status-card")
                    if card.one("status-card__head").attrs.get("data-path") == path)

    def _block(self, within, path):
        """The clamped block of ``path``'s own lines inside ``within``."""
        blocks = [block for block in within.all("reason-block")
                  if block.attrs.get("data-reason-node") == path]
        self.assertEqual(len(blocks), 1, path)
        return blocks[0]

    def test_a_lines_chips_stand_in_its_rail_on_every_surface_that_lists_it(self):
        # on the wall: a nested box's lines, after its head's row in the box, and a
        # card's own lines in its panel
        wall = self._page("/status")
        box = self._row(wall, "/ci/reviews", "status-node__self").parent
        self.assertTrue(box.has("tree-box"))
        self.assertEqual(self._line_rails(box, "status-node__reason"),
                         [["Copy", "raise"]] * 3)
        card = self._card(wall, "/ci")
        self.assertEqual(self._line_rails(self._block(card.one("status-panel"), "/ci"),
                                          "status-node__reason"),
                         [["Copy"]] * 2)          # the demo's filler declines a branch
        # on the branch's page: its own lines in its head, and the box as a card
        page = self._page("/status/ci")
        head = page.one("viewed-head")
        self.assertEqual(self._line_rails(head, "check-reason"), [["Copy"]] * 2)
        reviews = self._card(page, "/ci/reviews")
        self.assertEqual(self._line_rails(self._block(reviews, "/ci/reviews"),
                                          "status-node__reason"),
                         [["Copy", "raise"]] * 3)
        # on the leaf's own page: every line, uncapped, with the same two
        leaf = self._page("/status/ci/reviews")
        self.assertEqual(self._line_rails(leaf, "check-reason"),
                         [["Copy", "raise"]] * 3)

    def test_a_nodes_chip_stands_in_its_head_and_in_a_leaf_pages_frame_head(self):
        wall = self._page("/status")
        card_head = self._row(wall, "/db", "status-card__head")
        self.assertEqual(self._labels(card_head.one("node-actions")), ["file"])
        box_head = self._row(wall, "/ci/build", "status-node__self")
        self.assertEqual(self._labels(box_head.one("node-actions")), ["file"])
        # a node whose lines are members gets none: the line is the unit there
        self.assertEqual(
            self._labels(self._row(wall, "/ci/reviews", "status-node__self")
                         .one("node-actions")), [])
        # a leaf's page is framed as a branch's is, and its head's row carries the
        # node's actions as every head does (backlog #91 §3.5)
        page = self._page("/status/db")
        head_row = page.one("viewed-head").one("status-node__self")
        self.assertEqual(self._labels(head_row.one("node-actions")), ["file"])

    def test_the_refresh_draws_the_same_chips(self):
        for url in ("/status", "/status/ci"):
            with self.subTest(url=url):
                drawn = self._page(url)
                again = self._page(url + "?fragment=1")
                for page in (drawn, again):
                    page_chips = [(chip.text(), chip.attrs.get("href"))
                                  for chip in page.all("reason-action")
                                  + page.all("node-action")]
                    self.assertGreater(len(page_chips), 0, url)
                self.assertEqual(
                    [(c.text(), c.attrs.get("href")) for c in
                     drawn.all("reason-action") + drawn.all("node-action")],
                    [(c.text(), c.attrs.get("href")) for c in
                     again.all("reason-action") + again.all("node-action")])

    def test_a_chip_is_one_chip_wherever_it_stands(self):
        # a link, about the node whose row it stands in; the chips that are not links
        # are an admin's marks on the line — the one that pins it and the one that
        # marks it seen — which wear the chip's shape on purpose (`_own_lines.html`),
        # and say so by their own class
        for url in ("/status", "/status/ci", "/status/ci/reviews", "/status/db"):
            page = self._page(url)
            chips = page.all("reason-action") + page.all("node-action")
            self.assertGreater(len(chips), 0, url)
            for chip in chips:
                with self.subTest(url=url, chip=chip.text()):
                    if chip.tag == "summary":
                        self.assertTrue(chip.has("reason-pin__toggle")
                                        or chip.has("reason-ack__toggle"))
                        continue
                    self.assertEqual(chip.tag, "a")
                    href = chip.attrs.get("href", "")
                    self.assertTrue(href, chip.source()[:80])
                    row = chip.parent
                    while row is not None and "data-path" not in row.attrs \
                            and "data-node" not in row.attrs:
                        row = row.parent
                    if row is not None:          # the leaf page's lines have no row
                        path = row.attrs.get("data-path") or row.attrs["data-node"]
                        self.assertIn(path.replace("/", "%2F") if "%2F" in href
                                      else path, href)


if __name__ == "__main__":
    unittest.main()
