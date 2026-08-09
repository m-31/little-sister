"""The canonical incident-copy document."""
from datetime import datetime, timedelta
from unittest import TestCase

from little_sister.copy_status import format_copy_markdown, status_icon
from little_sister.render import render_markdown
from little_sister.status import StatusCode
from little_sister.tree import StatusTree


class CopyStatusTests(TestCase):
    def setUp(self) -> None:
        self.tree = StatusTree(root_name="Production")

    def _copy(self) -> str:
        return format_copy_markdown(self.tree.snapshot(""))

    def test_status_icon_roster_is_explicit(self):
        self.assertEqual(
            {code.name: status_icon(code) for code in StatusCode},
            {
                "MAINTENANCE": "🛠️",
                "OK": "✅",
                "WARN": "⚠️",
                "ERROR": "⛔",
                "UNDEFINED": "❓",
            },
        )

    def test_keeps_non_ok_leaves_and_their_minimum_ancestor_chain(self):
        self.tree.upsert("/aws/quality/healthy", StatusCode.OK)
        self.tree.upsert("/aws/quality/build", StatusCode.ERROR, "job failed")
        self.tree.upsert("/quiet/only", StatusCode.OK)

        copied = self._copy()

        self.assertEqual(
            copied,
            "- aws\n"
            "  - quality\n"
            "    - build ⛔\n"
            "      - job failed",
        )
        self.assertNotIn("Production", copied)  # the synthetic root is not useful
        self.assertNotIn("healthy", copied)
        self.assertNotIn("quiet", copied)

    def test_undefined_is_a_visible_non_ok_leaf(self):
        self.tree.upsert("/service/pending", StatusCode.UNDEFINED)
        self.assertIn("pending ❓", self._copy())

    def test_uses_authored_title_and_preserves_reason_markdown(self):
        self.tree.upsert(
            "/ci/build_1",
            StatusCode.WARN,
            ["See **owner**", "[run](https://ci.example/run/1)"],
        )
        self.tree.set_title("/ci/build_1", "Build _one_")

        copied = self._copy()
        rich = str(render_markdown(copied))

        self.assertIn("Build _one_ ⚠️", copied)
        self.assertIn("<em>one</em>", rich)
        self.assertIn("<strong>owner</strong>", rich)
        self.assertIn('href="https://ci.example/run/1"', rich)

    def test_names_cannot_break_out_of_the_outline(self):
        self.tree.upsert("/literal/*not-bold*[x]", StatusCode.ERROR)
        copied = self._copy()
        rich = str(render_markdown(copied))

        self.assertIn(r"\*not-bold\*\[x\]", copied)
        self.assertNotIn("<strong>", rich)
        self.assertNotIn("<a ", rich)

    def test_multiline_reason_stays_nested_and_renders_as_code(self):
        self.tree.upsert(
            "/service/api",
            StatusCode.ERROR,
            "```\nline one\n**literal**\n```",
        )
        copied = self._copy()
        rich = str(render_markdown(copied))

        self.assertIn("    - ```\n      line one", copied)
        self.assertIn("<pre>", rich)
        self.assertIn("**literal**", rich)
        self.assertNotIn("<strong>literal</strong>", rich)

    def test_node_and_reason_maintenance_are_attributed(self):
        expiry = datetime.now() + timedelta(days=1)
        self.tree.upsert(
            "/ci/reviews", StatusCode.ERROR,
            {"pr-1": "PR one failed", "pr-2": "PR two failed"},
        )
        self.tree.set_entry_maintenance(
            "/ci/reviews", "pr-1", "ticket\nfiled",
            expires_at=expiry, set_by="pan",
        )
        self.tree.upsert("/database", StatusCode.ERROR, "connection refused")
        self.tree.set_maintenance(
            "/database", "planned migration",
            expires_at=expiry, set_by="robin",
        )

        copied = self._copy()

        self.assertIn("reviews ⛔", copied)
        self.assertIn("PR one failed", copied)
        self.assertIn("🛠️ Maintenance — by pan, until", copied)
        self.assertIn("        - ticket\n          filed", copied)
        self.assertIn("database 🛠️ (reported ⛔)", copied)
        self.assertIn("🛠️ Maintenance — by robin, until", copied)
        self.assertIn("    - planned migration", copied)
        self.assertIn("connection refused", copied)

    def test_empty_and_all_ok_trees_produce_an_empty_document(self):
        self.assertEqual(self._copy(), "")
        self.tree.upsert("/service/api", StatusCode.OK)
        self.assertEqual(self._copy(), "")

    def test_raw_html_and_unsafe_links_stay_inert_in_rich_form(self):
        self.tree.upsert(
            "/service/api",
            StatusCode.ERROR,
            "<script>alert(1)</script> [bad](javascript:alert(2))",
        )
        rich = str(render_markdown(self._copy()))

        self.assertNotIn("<script>", rich)
        self.assertNotIn("<a ", rich)
        self.assertIn("&lt;script&gt;", rich)
