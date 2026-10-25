"""Template slots: what a dependent package may add to our pages, and what it may
not (ADR-0034)."""
import os
import unittest
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from jinja2 import TemplateNotFound

from little_sister import app as app_module
from little_sister import self_report, slots
from little_sister.checks.metadata import Stated
from little_sister.first_look import FirstLooks
from little_sister.nodes import NodeMeta
from little_sister.reasons import slug
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.demo_extension import (
    action,
    always,
    echoes,
    explodes,
    node_action,
    recorder,
)
from tests.page_tree import parse

DEMO = "tests.demo_extension"
TEMPLATE = "reason_action.html"
SECOND = "reason_action_two.html"
NODE_TEMPLATE = "node_action.html"


class RegistrationTests(TestCase):
    """The roster is closed, and every refusal is survivable."""

    def test_a_registration_is_recorded(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        registered = slots.extension_fillers()
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0].package, DEMO)
        self.assertEqual(registered[0].source, f"ext/{DEMO}/{TEMPLATE}")
        self.assertIn(DEMO, slots.packages())

    def test_the_library_fills_both_slots_itself(self):
        # the declarative action list (ADR-0038) is a filler like any other, and the
        # one thing a reset puts back
        builtin = [f for f in slots.all_fillers() if f.builtin]
        self.assertEqual({f.slot for f in builtin},
                         {"reason.actions", "node.actions"})
        self.assertEqual({f.package for f in builtin}, {"little_sister"})
        self.assertEqual(slots.extension_fillers(), ())

    def test_an_unknown_slot_name_is_refused_and_names_the_known_ones(self):
        with self.assertLogs("little_sister", level="WARNING") as logs:
            slots.register("reason.buttons", DEMO, TEMPLATE, action)
        self.assertEqual(slots.extension_fillers(), ())
        self.assertIn("reason.actions", "\n".join(logs.output))

    def test_a_template_the_package_does_not_ship_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            slots.register("reason.actions", DEMO, "not_there.html", action)
        self.assertEqual(slots.extension_fillers(), ())

    def test_a_package_that_is_not_importable_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            slots.register("reason.actions", "no.such.package", TEMPLATE, action)
        self.assertEqual(slots.extension_fillers(), ())

    def test_the_same_filler_twice_is_registered_once(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self.assertEqual(len(slots.extension_fillers()), 1)

    def test_a_filler_needs_no_provider(self):
        slots.register("reason.actions", DEMO, SECOND)
        self.assertIsNone(slots.extension_fillers()[0].context)

    def test_rendering_an_undeclared_slot_raises(self):
        # Our own bug, not a deployment's: the roster exists so a test catches it.
        with self.assertRaises(KeyError):
            slots.render("reason.buttons")


class LoaderTests(TestCase):
    """A registration adds a place's contents; it can never replace a template."""

    def setUp(self):
        self.loader = slots.ExtensionLoader()
        self.environment = app_module.app.jinja_env

    def test_a_core_template_name_is_not_this_loaders_business(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        with self.assertRaises(TemplateNotFound):
            self.loader.get_source(self.environment, "status.html")

    def test_an_unregistered_package_is_unreachable(self):
        with self.assertRaises(TemplateNotFound):
            self.loader.get_source(self.environment, f"ext/{DEMO}/{TEMPLATE}")

    def test_a_registered_package_resolves_under_its_prefix(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        source, _, _ = self.loader.get_source(
            self.environment, f"ext/{DEMO}/{TEMPLATE}")
        self.assertIn("reason-action", source)

    def test_nothing_resolves_outside_the_prefix(self):
        # `ext/<package>/<name>` and nothing else — no bare name, no half a path.
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        for name in (f"{DEMO}/{TEMPLATE}", "ext", f"ext/{DEMO}", TEMPLATE):
            with self.assertRaises(TemplateNotFound):
                self.loader.get_source(self.environment, name)

    def test_list_templates_reports_the_roster_it_serves(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self.assertIn(f"ext/{DEMO}/{TEMPLATE}", self.loader.list_templates())


class RenderTests(TestCase):
    """What a filler actually puts on the dashboard and the leaf page."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _body(self, url="/status"):
        return self.client.get(url).get_data(as_text=True)

    def test_no_registration_means_no_pixels(self):
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        body = self._body()
        self.assertIn("connection refused", body)
        self.assertNotIn("data-demo-action", body)
        # The frame is still emitted, and collapses in CSS when nothing filled it.
        self.assertIn('class="reason-actions"', body)

    def test_a_filler_renders_beside_a_leafs_reason_on_the_grid(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        body = self._body()
        self.assertIn('data-demo-action="first-filler"', body)
        self.assertIn("tracker.example.org/new?path=/db/main", body)
        # `surface` says which page, and the reason arrives unshortened.
        self.assertIn("grid#0: connection refused", body)

    def test_a_filler_renders_on_the_leaf_detail_page_too(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        self.assertIn("check#0: connection refused", self._body("/status/db/main"))

    def test_a_provider_returning_none_renders_nothing(self):
        # Placement policy is the filler's: this one declines a container.
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "down")
        self.tree.upsert("/db", StatusCode.ERROR, "a rolled-up reason")
        body = self._body()
        self.assertIn("a rolled-up reason", body)
        self.assertEqual(body.count('data-demo-action="first-filler"'), 1)

    def test_a_provider_that_raises_costs_its_button_and_nothing_else(self):
        slots.register("reason.actions", DEMO, TEMPLATE, explodes)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        with self.assertLogs("little_sister", level="ERROR"):
            body = self._body()
        self.assertIn("connection refused", body)
        self.assertNotIn("data-demo-action", body)

    def test_a_provider_that_raises_is_a_held_line_that_counts(self):
        """Per request and swallowed, so it used to be a log entry per page view
        and nothing else; now it is one line on the node while it recurs, with the
        count (backlog #70)."""
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)
        slots.register("reason.actions", DEMO, TEMPLATE, explodes)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        with self.assertLogs("little_sister", level="ERROR"):
            self._body()
            self._body()
        (line,) = self_report.runtime.lines()
        self.assertEqual(line.slug, slug("slot", DEMO, "reason.actions"))
        self.assertIs(line.code, StatusCode.WARN)
        self.assertIn("context provider", line.text)
        self.assertIn("renders nothing", line.text)
        self.assertIn("2 times in the last 10m", line.text)

    def test_provider_values_are_escaped_by_our_environment(self):
        # The provider hands back a plain string; our Jinja escapes it into the
        # attribute. A deployment never has to remember to (ADR-0018's posture).
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "<script>alert(1)</script>")
        body = self._body()
        self.assertIn("title=\"grid#0: &lt;script&gt;", body)
        self.assertNotIn("title=\"grid#0: <script>", body)

    def test_two_fillers_both_render_in_registration_order(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        slots.register("reason.actions", DEMO, SECOND, always)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "down")
        body = self._body()
        self.assertLess(body.index("first-filler"), body.index("second-filler"))

    def test_the_kiosk_renders_no_slot(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self._login()
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        body = self._body()
        self.assertIn("connection refused", body)
        self.assertNotIn("data-demo-action", body)

    def test_system_names_what_registered(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        self._login()
        body = self._body("/system/installed")
        self.assertIn("reason.actions", body)
        self.assertIn(DEMO, body)


class NodeActionTests(TestCase):
    """The second slot: an action whose subject is the whole node.

    It exists because ADR-0036 split a node's reasons into *members* and *prose*.
    On prose there is exactly one thing to act on and it is the node — a per-line
    control there would offer to raise a ticket about a stack trace.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _body(self, url="/status"):
        return self.client.get(url).get_data(as_text=True)

    def _prose(self):
        self.tree.upsert("/db", StatusCode.ERROR,
                         ["check error: connection refused", "Traceback…"])

    def _members(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, {"f-1": "one", "f-2": "two"})

    def test_the_slot_is_declared_with_its_context(self):
        # Adding a name to a slot's context is compatible; removing one is not, so
        # the contract is worth a test of its own (ADR-0034). `place` joined with the
        # head's row (ADR-0127 decision 3), so a filler can tell a card's head from
        # a nested box's; `written_out` and `details` with what a draft is written
        # with (ADR-0133 decisions 4 to 6), on both action slots.
        self.assertEqual(slots.SLOTS["node.actions"].context,
                         ("node", "surface", "place", "written_out", "details"))
        self.assertEqual(slots.SLOTS["reason.actions"].context,
                         ("node", "reason", "line", "index", "surface", "written_out",
                          "details"))
        self.assertIn("`place`", slots.SLOTS["node.actions"].where)

    def test_no_registration_means_no_pixels(self):
        self._login()
        self._prose()
        body = self._body()
        self.assertNotIn("data-demo-node-action", body)
        # the frame ships and collapses in CSS, like the reason rail
        self.assertIn('class="node-actions"', body)

    def test_a_filler_renders_in_the_card_head(self):
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self._prose()
        body = self._body()
        self.assertIn('data-demo-node-action="node-filler"', body)
        self.assertIn("tracker.example.org/new?node=/db", body)
        self.assertIn("grid: check error: connection refused", body)

    def test_a_filler_renders_on_the_leaf_page(self):
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self._prose()
        body = self._body("/status/db")
        self.assertIn('data-demo-node-action="node-filler"', body)
        self.assertIn("check: check error: connection refused", body)

    def test_a_filler_renders_on_a_nested_box_too(self):
        # A card is the top of a subtree and is usually a container with nothing of
        # its own to act on; the failing *leaf* sits in a nested box. Offering the
        # slot on cards alone put the chip nowhere the eye already was (ADR-0034,
        # 2026-08-03).
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self.tree.upsert("/hosts/alpha/disk", StatusCode.ERROR, "disk at 98%")
        body = self._body()
        # /hosts is the card; /hosts/alpha and its /disk leaf are nested boxes
        self.assertIn("tracker.example.org/new?node=/hosts/alpha/disk", body)

    def test_a_quiet_leaf_is_a_chip_whose_box_carries_the_slot(self):
        # A chip has no room for an action, and nothing quiet is worth acting on;
        # the node's box, drawn beside the chip and hidden until found (ADR-0127
        # decision 1), carries the slot as every box does, so a click that opens
        # the node shows the action without a request. The host's leaves start as
        # chips where its files say so (ADR-0128).
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self.tree.upsert("/hosts/alpha/disk", StatusCode.OK, "disk at 12%")
        app_module.first_looks = FirstLooks(
            (), {"/hosts/alpha": NodeMeta(look=Stated(chips=True))},
            app_module.config, self.tree.named_by_run)
        self.addCleanup(setattr, app_module, "first_looks", None)
        page = parse(self._body())
        node = next(node for node in page.all("tree-node")
                    if node.attrs.get("data-node") == "/hosts/alpha/disk")
        self.assertEqual(node.attrs.get("data-state"), "closed")
        chip = node.one("tree-chip")
        self.assertEqual(chip.all("node-action"), [])
        self.assertEqual(node.one("tree-hold").attrs.get("hidden"), "until-found")
        action = node.one("tree-box").one("node-actions").one("node-action")
        self.assertIn("node=/hosts/alpha/disk", action.attrs.get("href", ""))

    def test_the_filler_declines_a_node_whose_reasons_are_members(self):
        # placement policy stays with the filler: there the per-line control is
        # the right one, and this slot renders nothing
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self._members()
        body = self._body("/status/wiz")
        self.assertIn("one", body)
        self.assertNotIn("data-demo-node-action", body)

    def test_the_two_slots_are_independent(self):
        slots.register("reason.actions", DEMO, TEMPLATE, action)
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self._prose()
        body = self._body("/status/db")
        self.assertIn('data-demo-action="first-filler"', body)     # per line
        self.assertIn('data-demo-node-action="node-filler"', body)  # per node
        # one node action, two reason actions (one per prose line)
        self.assertEqual(body.count('data-demo-node-action'), 1)
        self.assertEqual(body.count('data-demo-action="first-filler"'), 2)

    def test_a_broken_filler_leaves_the_page_standing(self):
        slots.register("node.actions", DEMO, NODE_TEMPLATE, explodes)
        self._login()
        self._prose()
        with self.assertLogs("little_sister", level="ERROR"):
            body = self._body()
        self.assertIn("check error: connection refused", body)
        self.assertNotIn("data-demo-node-action", body)

    def test_the_kiosk_renders_no_node_action(self):
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        self._prose()
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        body = self._body()
        self.assertIn("check error", body)
        self.assertNotIn("data-demo-node-action", body)

    def test_provider_values_are_escaped_by_our_environment(self):
        # `echoes`, not a constant provider: the payload has to actually reach the
        # filler's template, or this passes on the markdown filter's escaping and
        # would keep passing with `| safe` in node_action.html.
        slots.register("node.actions", DEMO, NODE_TEMPLATE, echoes)
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, '<script>alert(1)</script>')
        body = self._body()
        self.assertIn("data-demo-node-action", body)            # it did render
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn("<script>alert(1)</script>", body)

    def test_an_attribute_payload_cannot_break_out(self):
        slots.register("node.actions", DEMO, NODE_TEMPLATE, echoes)
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, 'x" onmouseover="alert(1)')
        body = self._body()
        self.assertNotIn('onmouseover="alert(1)"', body)
        self.assertIn("&#34;", body)

    def test_system_names_the_second_slot_too(self):
        slots.register("node.actions", DEMO, NODE_TEMPLATE, node_action)
        self._login()
        body = self._body("/system/installed")
        self.assertIn("node.actions", body)
        self.assertIn(DEMO, body)


if __name__ == "__main__":
    unittest.main()


class AssetTests(TestCase):
    """What an extension may ship, and who puts the tag on the page (ADR-0037)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _body(self, url="/status"):
        return self.client.get(url).get_data(as_text=True)

    # ----- the sandbox -----

    def test_a_declared_asset_is_recorded_with_its_digest(self):
        slots.register_assets(DEMO, "demo.css", "demo.js")
        assets = slots.assets()
        self.assertEqual([a.member for a in assets], ["demo.css", "demo.js"])
        self.assertEqual([a.kind for a in assets], ["css", "js"])
        self.assertTrue(all(len(a.digest) == 8 for a in assets))

    def test_the_digest_is_the_content_not_our_version(self):
        slots.register_assets(DEMO, "demo.css")
        first = slots.assets()[0].digest
        slots.forget_fillers()
        slots.register_assets(DEMO, "demo.css")
        self.assertEqual(slots.assets()[0].digest, first)   # stable across runs
        self.assertNotEqual(first, slots.assets()[0].digest[::-1] + "x")

    def test_a_path_is_not_a_member_name(self):
        # the whole sandbox: an extension cannot name a path, so it cannot reach
        # outside what it ships
        for bad in ("../secret.js", "sub/dir.js", "/etc/passwd", "", "..",
                    "a b.js"):
            with self.subTest(member=bad):
                with self.assertLogs("little_sister", level="WARNING"):
                    slots.register_assets(DEMO, bad)
                self.assertEqual(slots.assets(), ())

    def test_only_css_and_js_are_served(self):
        with self.assertLogs("little_sister", level="WARNING"):
            slots.register_assets(DEMO, "demo.png")
        self.assertEqual(slots.assets(), ())

    def test_a_member_the_package_does_not_ship_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            slots.register_assets(DEMO, "not_there.js")
        self.assertEqual(slots.assets(), ())

    def test_an_unimportable_package_is_refused(self):
        with self.assertLogs("little_sister", level="WARNING"):
            slots.register_assets("no.such.package", "demo.js")
        self.assertEqual(slots.assets(), ())

    def test_the_same_asset_twice_is_registered_once(self):
        slots.register_assets(DEMO, "demo.js")
        slots.register_assets(DEMO, "demo.js")
        self.assertEqual(len(slots.assets()), 1)

    # ----- the tags, and who emits them -----

    def test_no_registration_means_no_tags(self):
        self._login()
        body = self._body()
        self.assertNotIn("/ext/", body)

    def test_the_library_emits_the_tags_in_registration_order(self):
        slots.register_assets(DEMO, "demo.css", "demo.js")
        self._login()
        body = self._body()
        css = f'<link href="/ext/{DEMO}/demo.css'
        js = f'<script src="/ext/{DEMO}/demo.js'
        self.assertIn(css, body)
        self.assertIn(js, body)
        self.assertLess(body.index(css), body.index(js))
        self.assertIn("defer", body)

    def test_the_url_carries_the_content_hash(self):
        slots.register_assets(DEMO, "demo.js")
        digest = slots.assets()[0].digest
        self._login()
        self.assertIn(f"demo.js?v={digest}", self._body())

    def test_every_page_gets_them_not_only_the_dashboard(self):
        slots.register_assets(DEMO, "demo.js")
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        for page in ("/status", "/status/db", "/events", "/handled", "/system"):
            with self.subTest(page=page):
                self.assertIn("/ext/", self._body(page))

    def test_the_login_page_carries_none(self):
        # _header.html is not on the login page, so nothing leaks pre-login
        slots.register_assets(DEMO, "demo.js")
        self.assertNotIn("/ext/", self.client.get("/login").get_data(as_text=True))

    def test_the_kiosk_loads_no_extension_assets(self):
        # it renders no slot, so there is nothing for the code to drive
        slots.register_assets(DEMO, "demo.js")
        self._login()
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.assertNotIn("/ext/", self._body())

    # ----- the route -----

    def test_the_route_serves_the_bytes_with_the_right_type(self):
        slots.register_assets(DEMO, "demo.js")
        self._login()
        response = self.client.get(f"/ext/{DEMO}/demo.js")
        self.assertEqual(response.status_code, 200)
        # exactly one charset: the table holds a bare mimetype and Flask adds it
        self.assertEqual(response.headers["Content-Type"],
                         "text/javascript; charset=utf-8")
        self.assertIn("__lsDemoExtensionLoaded", response.get_data(as_text=True))
        self.assertIn("immutable", response.headers["Cache-Control"])

    def test_an_unregistered_member_is_404(self):
        slots.register_assets(DEMO, "demo.js")
        self._login()
        self.assertEqual(self.client.get(f"/ext/{DEMO}/demo.css").status_code, 404)
        self.assertEqual(self.client.get("/ext/other.pkg/demo.js").status_code, 404)

    def test_the_route_is_login_gated(self):
        slots.register_assets(DEMO, "demo.js")
        response = self.client.get(f"/ext/{DEMO}/demo.js")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


class ContextContractTests(TestCase):
    """`SLOTS[name].context` is a promise to every filler, and until now nothing
    tied it to what the core templates actually hand over.

    A dropped name would have failed silently *inside* each provider — a
    `TypeError` on an unexpected keyword, swallowed by the containment that keeps a
    broken filler from taking the page down. This is the one place it can fail
    loudly instead.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        # a card with a reason, so both slots are reached
        self.tree.upsert("/db", StatusCode.ERROR, "boom")

    def _seen(self, slot, url):
        seen = []
        slots.register(slot, DEMO, NODE_TEMPLATE, recorder(seen))
        self.client.get(url)
        return seen

    def test_every_slot_receives_exactly_what_it_declares(self):
        for slot, url in (("reason.actions", "/status"),
                          ("node.actions", "/status"),
                          ("reason.actions", "/status/db"),
                          ("node.actions", "/status/db")):
            with self.subTest(slot=slot, page=url):
                slots.forget_fillers()
                seen = self._seen(slot, url)
                self.assertTrue(seen, f"{slot} was never rendered on {url}")
                for handed in seen:
                    self.assertEqual(sorted(handed), sorted(slots.SLOTS[slot].context))

    def test_the_depth_zero_card_offers_both_slots_too(self):
        # it renders the per-reason slot and used to skip the node one, so a
        # deployment's node action vanished at one depth setting and its reason
        # action did not
        self.tree.upsert("/system/alpha", StatusCode.OK)
        self.tree.upsert("/system", StatusCode.ERROR, "the branch check failed")
        for slot in ("reason.actions", "node.actions"):
            with self.subTest(slot=slot):
                slots.forget_fillers()
                seen = self._seen(slot, "/status/system?depth=0")
                self.assertTrue(seen, f"{slot} is missing at depth 0")
                for handed in seen:
                    self.assertEqual(sorted(handed), sorted(slots.SLOTS[slot].context))

    def test_the_surface_names_are_the_documented_ones(self):
        for url, surface in (("/status", "grid"), ("/status/db", "check")):
            with self.subTest(page=url):
                slots.forget_fillers()
                seen = self._seen("node.actions", url)
                self.assertEqual({handed["surface"] for handed in seen}, {surface})

    def test_the_place_names_are_the_documented_ones(self):
        # a card's head, a nested box's and a page's frame head (ADR-0127 decision
        # 3), a leaf's page framed as a branch's is (backlog #91 §3.5): the filler is
        # called for every node the grid draws, open or closed, and told where
        self.tree.upsert("/db/disk/smart", StatusCode.OK)
        for url, places in (("/status", {"/db": "card", "/db/disk": "box",
                                         "/db/disk/smart": "box"}),
                            ("/status/db", {"/db": "frame", "/db/disk": "card",
                                            "/db/disk/smart": "box"}),
                            ("/status/db?depth=0", {"/db": "card"}),
                            ("/status/db/disk/smart", {"/db/disk/smart": "frame"})):
            with self.subTest(page=url):
                slots.forget_fillers()
                seen = self._seen("node.actions", url)
                self.assertEqual(
                    {handed["node"].path: handed["place"] for handed in seen}, places)


class DraftingTests(TestCase):
    """What a filler drafts with (ADR-0133 decisions 4 to 6). Beside the node, both
    action slots hand over two functions that write the node's texts and its *About*
    card out of the instance as the Copy document does: a status's sign as its word
    and cue, a link in the short form to the absolute address of a handbook — the
    node's own, or for a detail given down, the handbook of the node it is given on.
    A filler calls them for a draft it makes; one that does not pays nothing."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.addCleanup(slots.forget_fillers)
        self.tree.set_details("/servers", (("contact", "[the runbook](handbook#who)"),))
        self.tree.set_handbook("/servers", "## Who\n")
        self.tree.upsert("/servers/db", StatusCode.ERROR,
                         "{error}: down, [see](handbook#restart)",
                         type_details=(("host", "`db-1`"),))

    def _drafts(self, slot, *, url="/status/servers/db", asks=True):
        drafts: list = []

        def provider(*, node, written_out, details):
            if asks and node.path == "/servers/db":
                drafts.append((written_out(node.reason[0]),
                               written_out("{warn} {nobody}", inline=True),
                               details()))
            return None

        slots.register(slot, DEMO, NODE_TEMPLATE, provider)
        self.client.get(url)
        return drafts

    def test_a_filler_writes_the_nodes_texts_and_its_card_out(self):
        for slot in ("node.actions", "reason.actions"):
            with self.subTest(slot=slot):
                slots.forget_fillers()
                drafts = self._drafts(slot)
                self.assertTrue(drafts, f"{slot} handed nothing over")
                for line, word, details in drafts:
                    self.assertEqual(
                        line, "error ⛔: down, "
                              "[see](http://localhost/handbook/servers/db#restart)")
                    # a name no status has is a text's own
                    self.assertEqual(word, "warn ⚠️ {nobody}")
                    # the type's first, then what /servers gives down, its link into
                    # the handbook of the node it is given on
                    self.assertEqual(details, (
                        ("host", "`db-1`"),
                        ("contact",
                         "[the runbook](http://localhost/handbook/servers#who)")))

    def test_a_filler_that_does_not_ask_pays_nothing(self):
        # a slot is filled for every node at every render, so the card is resolved
        # for the draft that asks for it and for nobody else
        asked: list = []
        resolve = self.tree.details

        def counted(path):
            asked.append(path)
            return resolve(path)

        self.tree.details = counted
        self._drafts("node.actions", url="/status", asks=False)
        self.assertNotIn("/servers/db", asked)
        slots.forget_fillers()
        self._drafts("node.actions", url="/status")
        self.assertIn("/servers/db", asked)

    def test_outside_a_request_a_short_form_stays_as_written(self):
        # with no request there is no base to write an address from
        with app_module.app.app_context():
            drafting = app_module._drafting(self.tree.snapshot("/servers/db"))
            self.assertEqual(drafting["written_out"]("[see](handbook#restart)"),
                             "[see](handbook#restart)")
            self.assertEqual(drafting["details"]()[1],
                             ("contact", "[the runbook](handbook#who)"))


class ContextGrowthTests(TestCase):
    """A slot's context grows, and a provider written before it grew keeps working.

    `reason.actions` gained `line` when a control needed a slug rather than a text.
    On a **published** seam that must not cost a deployment its chips on an upgrade
    of ours, so a provider is handed exactly what it asks for.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _render(self, provider):
        slots.register("reason.actions", DEMO, TEMPLATE, provider)
        self.tree.upsert("/db/main", StatusCode.ERROR, "connection refused")
        return self.client.get("/status").get_data(as_text=True)

    def test_a_provider_that_predates_the_new_name_still_renders(self):
        # `action` spells out (node, reason, index, surface) — the signature every
        # filler written before `line` existed has. It must neither raise nor lose
        # its chip.
        with self.assertNoLogs("little_sister", level="ERROR"):
            body = self._render(action)

        self.assertIn('data-demo-action="first-filler"', body)

    def test_a_provider_that_asks_for_everything_gets_the_new_name(self):
        seen: list = []
        self._render(recorder(seen))

        self.assertTrue(seen)
        for handed in seen:
            self.assertIn("line", handed)
            self.assertEqual(getattr(handed["line"], "text", None),
                             "connection refused")

    def test_a_provider_may_ask_for_only_what_it_uses(self):
        seen: list = []

        def narrow(*, line: object) -> dict[str, object]:
            seen.append(line)
            return {"label": "narrow", "url": "https://tracker.example.org/new",
                    "summary": "narrow"}

        with self.assertNoLogs("little_sister", level="ERROR"):
            body = self._render(narrow)

        self.assertIn('data-demo-action="first-filler"', body)
        self.assertEqual([getattr(one, "slug", "") for one in seen],
                         [self.tree.snapshot("/db/main").reasons[0].slug])

    def test_a_callable_with_no_readable_signature_still_gets_everything(self):
        # A provider need not be a plain function — a `functools.partial` over a
        # builtin, a C callable, an object with `__call__`. Where the signature
        # cannot be read there is nothing to filter by, and the honest fallback is
        # the whole context: the filler either copes or is contained like any other.
        class Callable:
            def __init__(self) -> None:
                self.seen: dict = {}

            def __call__(self, **context: object):
                self.seen = dict(context)
                return {"label": "opaque",
                        "url": "https://tracker.example.org/new",
                        "summary": "opaque"}

        provider = Callable()
        provider.__signature__ = property()   # unreadable by `inspect.signature`

        with self.assertNoLogs("little_sister", level="ERROR"):
            self._render(provider)

        self.assertEqual(sorted(provider.seen),
                         sorted(slots.SLOTS["reason.actions"].context))
