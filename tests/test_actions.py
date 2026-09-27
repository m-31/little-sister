"""The declarative action list — `config/actions.yaml` (ADR-0038).

A filler the library itself ships, so the common case — a link with the node's
details in the query string — needs no deployment code at all.
"""
import os
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
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

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

    def test_system_names_the_built_in_filler(self):
        self._login()
        body = self._body("/system")
        self.assertIn("built-in", body)
        self.assertIn("node.actions", body)


if __name__ == "__main__":
    unittest.main()
