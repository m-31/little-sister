"""The canonical incident-copy documents — the tree's, and one node's."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from unittest import TestCase
from zoneinfo import ZoneInfo

from little_sister.copy_status import (
    TimeStyle,
    format_copy_markdown,
    format_node_markdown,
    format_reason_markdown,
    status_icon,
    written_out,
)
from little_sister.reasons import Entry
from little_sister.render import render_markdown
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

# A fixed clock for the documents, standing in for the deployment's configured
# timezone: one hour off UTC in winter and two in summer, so a test can tell an
# offset that was computed from the instant apart from one that was pasted on.
BERLIN = TimeStyle(ZoneInfo("Europe/Berlin"))


def _utc(*moment: int) -> datetime:
    """An instant, by its date and its time in UTC."""
    return datetime(*moment, tzinfo=UTC)


class CopyStatusTests(TestCase):
    def setUp(self) -> None:
        self.tree = StatusTree(root_name="Production")

    def _copy(self) -> str:
        return format_copy_markdown(self.tree.snapshot(""), BERLIN)

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

    def test_a_text_writes_a_status_it_names_as_the_document_does(self):
        # the library's one function for a text leaving the instance (ADR-0133
        # decision 5): a placeholder the page draws as a sign is written in this
        # document's words — the word and the portable cue — and the rest stays
        self.assertEqual(
            written_out("{error}: restart the gateway; {WARN} waits, `{ok}` stays."),
            "error ⛔: restart the gateway; warn ⚠️ waits, `{ok}` stays.")
        for code in StatusCode:
            with self.subTest(status=code.name):
                self.assertEqual(written_out(f"{{{code.name.lower()}}}"),
                                 f"{code.name.lower()} {status_icon(code)}")
        # as the page renders the text: inline, as a title is, indented words are no
        # code block, and the page draws their sign
        self.assertEqual(written_out("    {error} when it fails", inline=True),
                         "    error ⛔ when it fails")
        self.assertEqual(written_out("    {error} when it fails"),
                         "    {error} when it fails")
        # as the head of a node's document says the status it reported
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")
        node = self.tree.snapshot("/svc/api")
        assert node is not None
        self.assertIn(f"**Reported:** {written_out('{error}')}",
                      format_node_markdown(node, BERLIN))

    def test_every_text_it_carries_writes_out_the_statuses_it_names(self):
        # one renderer draws a sign in every text the page shows (ADR-0018 decision
        # 14), so both documents write each out as they write a status: a line, a
        # title, an admin's note and what the run found
        self.tree.upsert("/svc/api", StatusCode.ERROR, "the probe said {error}",
                         report="- the last run {warn}")
        self.tree.set_title("/svc/api", "Gateway {ok}")
        self.tree.set_maintenance("/svc/api", "back {OK} by noon", set_by="lex",
                                  expires_at=datetime.now(UTC) + timedelta(days=1))
        node = self.tree.snapshot("/svc/api")
        assert node is not None
        tree_document = self._copy()
        node_document = format_node_markdown(node, BERLIN)
        for document in (tree_document, node_document):
            with self.subTest(document=document[:20]):
                self.assertIn("Gateway ok ✅", document)
                self.assertIn("the probe said error ⛔", document)
                self.assertIn("back ok ✅ by noon", document)
                self.assertNotIn("{", document)
        self.assertIn("- the last run warn ⚠️", node_document)

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

    def test_a_title_that_only_repeats_the_name_does_not_label_the_item(self):
        # Same rule as the web surfaces, one predicate (`titles.py`).  The document
        # is read with no chips and no styling, where `critical` alone says
        # everything *Critical* would.
        self.tree.upsert("/github/severity/critical", StatusCode.ERROR, "one alert")
        self.tree.set_title("/github/severity/critical", "Critical")

        copied = self._copy()

        self.assertIn("- critical ⛔", copied)
        self.assertNotIn("Critical", copied)

    def test_a_title_with_no_word_in_it_comes_with_its_name(self):
        # ADR-0061. This document is read with no chips and no styling, so a title
        # that stands in for the name has to *be* a name — and 🔴 is not one. The
        # color survives; the word is what a reader cannot reconstruct without it.
        self.tree.upsert("/github/severity/critical", StatusCode.ERROR, "one alert")
        self.tree.set_title("/github/severity/critical", "🔴")

        copied = self._copy()

        self.assertIn("- critical 🔴 ⛔", copied)

    def test_a_name_drawn_beside_a_glyph_is_still_escaped(self):
        # The name half is structural data either way. Before this rule the name
        # only reached the document when there was no title at all, so this is a
        # path that could not previously carry an unescaped one.
        self.tree.upsert("/literal/*not-bold*", StatusCode.ERROR)
        self.tree.set_title("/literal/*not-bold*", "🔴")

        copied = self._copy()

        self.assertIn(r"\*not-bold\* 🔴", copied)
        self.assertNotIn("<em>", str(render_markdown(copied)))

    def test_a_word_still_labels_the_item_alone(self):
        # The rule is narrow on purpose: a title that says something is still a
        # better name for the node than the node's own name.
        self.tree.upsert("/services/api", StatusCode.WARN, "slow")
        self.tree.set_title("/services/api", "Order intake")

        copied = self._copy()

        self.assertIn("- Order intake ⚠️", copied)
        self.assertNotIn("api Order intake", copied)

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
        expiry = datetime.now(UTC) + timedelta(days=1)
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


class TimeStyleTests(TestCase):
    """The one thing a copied instant has that a rendered one does not."""

    def test_an_instant_carries_the_offset_in_force_at_that_instant(self):
        # Not a constant pasted onto the string: the same zone is one hour off
        # UTC in January and two in August, and a reader elsewhere is entitled to
        # the one that was actually true.
        self.assertEqual(BERLIN.at(_utc(2026, 1, 15, 9, 0)),
                         "2026-01-15 10:00:00 +01:00")
        self.assertEqual(BERLIN.at(_utc(2026, 8, 15, 9, 0)),
                         "2026-08-15 11:00:00 +02:00")

    def test_an_instant_reads_alike_whatever_zone_it_was_built_in(self):
        # What the tree stores is an instant (ADR-0120): the document writes the
        # one moment, in its own zone, however the instant came to be held.
        held = _utc(2026, 1, 15, 9, 0)
        for built in (held.astimezone(ZoneInfo("America/New_York")),
                      held.astimezone(ZoneInfo("Asia/Kathmandu"))):
            self.assertEqual(BERLIN.at(built), "2026-01-15 10:00:00 +01:00")

    def test_absent_answers_like_the_page(self):
        self.assertEqual(BERLIN.at(None), "—")

    def test_the_zone_and_the_format_are_the_deployments(self):
        style = TimeStyle(ZoneInfo("UTC"), "%H:%M")
        self.assertEqual(
            style.at(datetime(2026, 8, 15, 9, 30,
                              tzinfo=timezone(timedelta(hours=2)))),
            "07:30 +00:00")

    def test_the_tree_document_dates_a_pin_the_same_way(self):
        # One formatter, so /copy gained the offset with the node document: an
        # expiry read in another office is exactly the instant that needs it.
        tree = StatusTree(root_name="Production")
        tree.upsert("/database", StatusCode.ERROR, "connection refused")
        tree.set_maintenance(
            "/database", "planned migration",
            expires_at=_utc(2026, 1, 20, 9, 0),
            set_by="robin")

        copied = format_copy_markdown(tree.snapshot(""), BERLIN)

        self.assertIn("🛠️ Maintenance — by robin, until "
                      "2026-01-20 10:00:00 +01:00", copied)


class NodeCopyTests(TestCase):
    """One leaf as a hand-off: what only the detail page knows."""

    def setUp(self) -> None:
        self.tree = StatusTree(root_name="Production")

    def _leaf(self, path="/services/api", **facts):
        """The node's snapshot with its observation pinned to a fixed instant.

        The tree stamps `now`, which would make an asserted offset a statement
        about the month the suite runs in; the copy document has to be readable
        in January and August alike, so the instants here are chosen, not taken.
        """
        node = self.tree.snapshot(path)
        assert node is not None
        return replace(node, **facts)

    def _document(self, node, since=None) -> str:
        return format_node_markdown(node, BERLIN, since)

    def test_the_document_names_the_node_its_path_and_the_reading(self):
        self.tree.upsert("/services/api", StatusCode.ERROR, "connection refused")

        document = self._document(self._leaf())

        self.assertTrue(document.startswith("## api ⛔\n"), document)
        self.assertIn("- **Path:** /services/api", document)
        self.assertIn("- **Reported:** error ⛔", document)
        self.assertIn("**Reasons**", document)
        self.assertIn("- connection refused", document)

    def test_the_title_labels_the_document_and_the_path_keeps_the_name(self):
        self.tree.upsert("/services/api", StatusCode.WARN, "slow")
        self.tree.set_title("/services/api", "Order _intake_")

        document = self._document(self._leaf())

        self.assertTrue(document.startswith("## Order _intake_ ⚠️\n"), document)
        self.assertIn("- **Path:** /services/api", document)

    def test_the_observation_and_its_period_carry_their_zone(self):
        self.tree.upsert("/services/api", StatusCode.ERROR, "down")

        document = self._document(
            self._leaf(timestamp=_utc(2026, 1, 15, 9, 0)),
            since=_utc(2026, 1, 15, 7, 30))

        self.assertIn("- **Status error** since 2026-01-15 08:30:00 +01:00\n"
                      "- **Last observed:** 2026-01-15 10:00:00 +01:00", document)

    def test_a_status_that_still_holds_has_no_until(self):
        # The later instant is the latest reading, not an end: a period that has
        # not ended says since when, and when it was last observed — also where the
        # two are one instant, which read "from 09:00 until 09:00".
        self.tree.upsert("/services/api", StatusCode.ERROR, "down")

        for since in (_utc(2026, 1, 15, 7, 30), _utc(2026, 1, 15, 9, 0)):
            with self.subTest(since=since):
                document = self._document(
                    self._leaf(timestamp=_utc(2026, 1, 15, 9, 0)), since=since)
                self.assertIn("- **Status error** since ", document)
                self.assertIn("- **Last observed:** 2026-01-15 10:00:00 +01:00",
                              document)
                self.assertNotIn("until", document)

    def test_a_period_the_log_holds_no_start_of_holds_since_before_its_oldest_event(
            self):
        # Where the log keeps no change of the node, the furthest back it can vouch
        # that nothing changed is its oldest event (ADR-0099 decision 1).
        self.tree.upsert("/services/api", StatusCode.ERROR, "down")

        document = format_node_markdown(
            self._leaf(timestamp=_utc(2026, 1, 15, 9, 0)), BERLIN,
            _utc(2026, 1, 15, 7, 30), before=True)

        self.assertIn("- **Status error** since before 2026-01-15 08:30:00 +01:00\n"
                      "- **Last observed:** 2026-01-15 10:00:00 +01:00", document)

    def test_without_a_transition_of_its_own_it_reports_the_observation(self):
        # ADR-0027: no period to bound, so it does not invent a from/until of one
        # instant — the same answer the page's Time card gives.
        self.tree.upsert("/services/api", StatusCode.ERROR, "down")

        document = self._document(self._leaf(timestamp=_utc(2026, 1, 15, 9, 0)))

        self.assertIn("- **Observed:** 2026-01-15 10:00:00 +01:00", document)
        self.assertNotIn("from", document)

    def test_a_node_no_check_has_written_says_so(self):
        self.tree.upsert("/services/api", StatusCode.UNDEFINED)

        document = self._document(self._leaf(timestamp=None))

        self.assertIn("- **Not yet observed.**", document)
        self.assertNotIn("—", document)

    def test_the_run_facts_are_the_pages_own_words(self):
        self.tree.upsert("/services/api", StatusCode.ERROR, "down",
                         frequency_seconds=900)
        self.tree.set_check_mount("/services/api")
        self.tree.set_run_facts("/services/api", wall_seconds=3.14159,
                                next_run_at=_utc(2026, 1, 15, 9, 15))

        document = self._document(self._leaf())

        self.assertIn("- **Next update:** 2026-01-15 10:15:00 +01:00", document)
        self.assertIn("- **Last run took:** 3.1 s", document)
        # A *configured* interval in the units the config wrote it in — `15m`,
        # not the `15m 0s` a measured span would read (`spans.py`).
        self.assertIn("- **Checked every:** 15m", document)

    def test_a_node_with_no_period_states_the_freshness_it_promises(self):
        # ADR-0081: the clipboard document and the page say the same thing here,
        # which is the whole reason the rule is one rule — "Checked every 1s" on a
        # node nothing checks was written in both places and wrong in both.
        self.tree.upsert("/little-sister/startup", StatusCode.OK,
                         stale_after=31.0)

        document = self._document(self._leaf(path="/little-sister/startup"))

        self.assertIn("- **Goes stale after:** 31s", document)
        self.assertNotIn("Checked every", document)

    def test_a_stale_node_says_how_long_ago_it_was_observed(self):
        # Observed, as the Time card says it: a node the instance re-asserts on its
        # own tick goes stale too, and nothing checks it.
        self.tree.upsert("/services/api", StatusCode.ERROR, "down")

        # both flags, as the tree hands over a node whose own reading is the stale one
        document = self._document(self._leaf(stale=True, own_stale=True,
                                             age_seconds=7620))

        self.assertIn("- **Stale** — last observed 2h 7m ago", document)

    def test_a_pin_keeps_the_measurement_and_says_a_pin_is_in_force(self):
        # A pin changes what the tree *reports*; it does not change what the check
        # *measured*, and a hand-off is about the measurement.
        self.tree.upsert("/services/api", StatusCode.ERROR, "connection refused")
        self.tree.set_maintenance(
            "/services/api", "waiting on the vendor",
            expires_at=_utc(2026, 1, 20, 9, 0),
            set_by="robin")

        document = self._document(self._leaf())

        self.assertTrue(document.startswith("## api ⛔\n"), document)
        # One statement in three lines, and they stay together: the reading, what
        # the tree shows instead, and whose pin makes it show that. Five time
        # facts in between is where a reader stops connecting them.
        self.assertIn(
            "- **Reported:** error ⛔\n"
            "- **Shown as:** maintenance 🛠️ — a maintenance pin is in force; the "
            "reported reading above is what the check measured.\n"
            "- 🛠️ Maintenance — by robin, until 2026-01-20 10:00:00 +01:00\n"
            "  - waiting on the vendor\n",
            document)
        self.assertIn("- connection refused", document)

    def test_an_unpinned_node_claims_no_pin(self):
        self.tree.upsert("/services/api", StatusCode.ERROR, "connection refused")

        document = self._document(self._leaf())

        self.assertNotIn("Shown as", document)
        self.assertNotIn("Maintenance", document)

    def test_a_pinned_entry_is_attributed_beside_its_own_line(self):
        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"pr-1": "PR one failed", "pr-2": "PR two failed"})
        self.tree.set_entry_maintenance(
            "/ci/reviews", "pr-1", "ticket filed",
            expires_at=_utc(2026, 1, 20, 9, 0),
            set_by="pan")

        document = self._document(self._leaf("/ci/reviews"))

        self.assertIn("- PR one failed\n  - 🛠️ Maintenance — by pan, until "
                      "2026-01-20 10:00:00 +01:00\n    - ticket filed", document)
        self.assertIn("- PR two failed", document)

    def test_reason_lines_are_carried_in_full_and_keep_their_markdown(self):
        # The truncated API error this feature started from: what the page shows
        # uncapped, the document carries whole, fence and all.
        self.tree.upsert(
            "/services/api", StatusCode.ERROR,
            ["upstream said **no**",
             "```\nHTTP 502\nbody: {\"error\": \"gateway\"}\n```"])

        document = self._document(self._leaf())
        rich = str(render_markdown(document))

        self.assertIn("- upstream said **no**", document)
        self.assertIn("- ```\n  HTTP 502\n  body: {\"error\": \"gateway\"}\n  ```",
                      document)
        self.assertIn("<strong>no</strong>", rich)
        self.assertIn("<pre>", rich)
        self.assertIn("gateway", rich)

    def test_the_report_and_the_configuration_render_as_themselves(self):
        # Both are authored Markdown (ADR-0018) and land at the margin rather than
        # nested inside a list item, so a bulleted configuration is a list in the
        # pasted document instead of literal punctuation.
        self.tree.upsert(
            "/services/api", StatusCode.ERROR, "down",
            report="- 12 endpoints probed\n- 1 failed",
            config="- **url:** https://api.example/health")

        document = self._document(self._leaf())
        rich = str(render_markdown(document))

        self.assertIn("**Report**\n\n- 12 endpoints probed\n- 1 failed", document)
        self.assertIn("**Configuration**\n\n- **url:** https://api.example/health",
                      document)
        self.assertIn("<li>12 endpoints probed</li>", rich)
        self.assertIn("<strong>url:</strong>", rich)

    def test_a_secret_reference_stays_a_reference(self):
        # The document is pasted into tickets and chats. A check writes the
        # reference into its configuration, never the value (ADR-0023), and the
        # copy is one more surface that must not be where that changes.
        self.tree.upsert(
            "/services/api", StatusCode.ERROR, "unauthorized",
            config="- **url:** https://api.example/health\n"
                   "- **token:** env://API_TOKEN")

        document = self._document(self._leaf())

        self.assertIn("env://API_TOKEN", document)
        self.assertNotIn("s3cr3t", document)

    def test_a_path_cannot_break_out_of_the_document(self):
        self.tree.upsert("/literal/*not-bold*[x]", StatusCode.ERROR)

        document = self._document(self._leaf("/literal/*not-bold*[x]"))
        rich = str(render_markdown(document))

        self.assertIn(r"**Path:** /literal/\*not-bold\*\[x\]", document)
        self.assertNotIn("<strong>not-bold</strong>", rich)
        self.assertNotIn("<a ", rich)

    def test_raw_html_in_a_reason_stays_inert_in_rich_form(self):
        self.tree.upsert(
            "/services/api", StatusCode.ERROR,
            "<script>alert(1)</script> [bad](javascript:alert(2))")

        rich = str(render_markdown(self._document(self._leaf())))

        self.assertNotIn("<script>", rich)
        self.assertNotIn("<a ", rich)
        self.assertIn("&lt;script&gt;", rich)

    def test_a_healthy_leaf_still_copies(self):
        # Unlike the tree document, which drops what is OK: this one is asked for
        # by somebody standing on that node's page, and "nothing to copy" there
        # would be a button that does nothing.
        self.tree.upsert("/services/api", StatusCode.OK, "all good")

        document = self._document(self._leaf())

        self.assertTrue(document.startswith("## api ✅\n"), document)
        self.assertIn("- all good", document)


class CodedLineTests(TestCase):
    """A line's own claim, in both documents (ADR-0042).

    The check's node code answers for an uncoded line and the node has already
    said it; a **coded** line disagrees with its node on purpose, and a document
    that dropped that would hand somebody a green workflow rendered as a failure.
    """

    def setUp(self) -> None:
        self.tree = StatusTree(root_name="Production")

    def _workflows(self, path="/ci/actions"):
        self.tree.upsert(path, StatusCode.ERROR, [
            Entry("build", "build #4215 failed", code=StatusCode.ERROR,
                  running=True),
            Entry("lint", "lint #4215 passed", code=StatusCode.OK),
            Entry("note", "two runners are offline"),
        ], members=True)

    def _node(self, path="/ci/actions") -> str:
        node = self.tree.snapshot(path)
        assert node is not None
        return format_node_markdown(node, BERLIN)

    def _tree(self) -> str:
        return format_copy_markdown(self.tree.snapshot(""), BERLIN)

    def test_a_coded_line_carries_its_own_cue_and_an_uncoded_one_carries_none(self):
        self._workflows()

        for name, document in (("node", self._node()), ("tree", self._tree())):
            with self.subTest(document=name):
                self.assertIn("⛔ (running) build #4215 failed", document)
                self.assertIn("✅ lint #4215 passed", document)
                # No cue on the line that declared no code: it carries the node's,
                # and the node's own line has already said what that is.
                self.assertIn("- two runners are offline", document)
                self.assertNotIn("⛔ two runners", document)

    def test_a_healthy_line_survives_under_a_failing_node(self):
        # The case ADR-0042 exists for: without the line's own cue, `lint passed`
        # sits under an ⛔ node and reads as one more failure.
        self._workflows()

        document = self._node()

        self.assertTrue(document.startswith("## actions ⛔\n"), document)
        self.assertIn("✅ lint #4215 passed", document)

    def test_work_in_flight_is_written_out_because_there_is_no_italic(self):
        self.tree.upsert("/ci/actions", StatusCode.WARN, [
            Entry("build", "build #4215 running 2m", code=StatusCode.WARN,
                  running=True),
        ], members=True)

        document = self._node()

        self.assertIn("- ⚠️ (running) build #4215 running 2m", document)
        # A word, not emphasis: ADR-0042 turned `*…*` down as a channel.
        self.assertNotIn("*build", document)

    def test_a_cue_never_breaks_the_fence_its_line_opens(self):
        # The one construct that cannot share a line. Prefixing it inline would
        # leave the fence unopened and the closing one meaning something else.
        self.tree.upsert("/ci/actions", StatusCode.ERROR, [
            Entry("build", "```\nHTTP 502\n**literal**\n```",
                  code=StatusCode.ERROR),
        ], members=True)

        document = self._node()
        rich = str(render_markdown(document))

        self.assertIn("- ⛔\n  ```\n  HTTP 502\n  **literal**\n  ```", document)
        self.assertIn("<pre>", rich)
        self.assertIn("**literal**", rich)          # inside the fence, not bold
        self.assertNotIn("<strong>literal</strong>", rich)

    def test_a_pinned_coded_line_keeps_both_its_cue_and_its_attribution(self):
        self._workflows()
        self.tree.set_entry_maintenance(
            "/ci/actions", "build", "rebuilding the runner",
            expires_at=_utc(2026, 1, 20, 9, 0),
            set_by="pan")

        document = self._node()

        self.assertIn("- ⛔ (running) build #4215 failed\n"
                      "  - 🛠️ Maintenance — by pan, until "
                      "2026-01-20 10:00:00 +01:00\n"
                      "    - rebuilding the runner", document)


class ReasonCopyTests(TestCase):
    """One line, handed over on its own — the finding an operator files a ticket
    about, without the other nineteen."""

    def setUp(self) -> None:
        self.tree = StatusTree(root_name="Production")
        self.tree.upsert("/ci/reviews", StatusCode.ERROR, [
            Entry("pr-412", "acme/api-pr-412 review overdue",
                  code=StatusCode.ERROR),
            Entry("pr-77", "acme/web-pr-77 review overdue"),
        ], members=True, frequency_seconds=900,
            report="- 41 pull requests scanned",
            config="- **token:** env://GITHUB_TOKEN")

    def _document(self, slug="pr-412") -> str:
        node = self.tree.snapshot("/ci/reviews")
        assert node is not None
        node = replace(node, timestamp=_utc(2026, 1, 15, 9, 0))
        line = next(r for r in node.reasons if r.slug == slug)
        return format_reason_markdown(node, line, BERLIN)

    def test_it_carries_the_line_and_where_it_came_from(self):
        document = self._document()

        self.assertEqual(
            document,
            "## reviews ⛔\n"
            "\n"
            "- **Path:** /ci/reviews\n"
            "- **Observed:** 2026-01-15 10:00:00 +01:00\n"
            "\n"
            "**Finding**\n"
            "\n"
            "- ⛔ acme/api-pr-412 review overdue")

    def test_it_carries_only_the_line_it_was_asked_for(self):
        document = self._document()

        self.assertNotIn("pr-77", document)
        self.assertNotIn("web-pr-77", document)

    def test_the_nodes_own_facts_stay_with_the_nodes_own_document(self):
        # The run's facts, the report and the configuration answer questions about
        # the *node*; the button that carries them is one click away on the same
        # page. Keeping the configuration out is also what keeps a secret
        # reference (ADR-0023) from ever reaching this document.
        document = self._document()

        self.assertNotIn("Checked every", document)
        self.assertNotIn("Report", document)
        self.assertNotIn("Configuration", document)
        self.assertNotIn("GITHUB_TOKEN", document)

    def test_a_pinned_line_brings_its_pin_with_it(self):
        self.tree.set_entry_maintenance(
            "/ci/reviews", "pr-412", "waiting on the author",
            expires_at=_utc(2026, 1, 20, 9, 0),
            set_by="pan")

        document = self._document()

        self.assertIn("- ⛔ acme/api-pr-412 review overdue\n"
                      "  - 🛠️ Maintenance — by pan, until "
                      "2026-01-20 10:00:00 +01:00\n"
                      "    - waiting on the author", document)

    def test_an_unobserved_node_states_no_instant_at_all(self):
        node = self.tree.snapshot("/ci/reviews")
        assert node is not None
        node = replace(node, timestamp=None)

        document = format_reason_markdown(node, node.reasons[0], BERLIN)

        self.assertNotIn("Observed", document)
        self.assertNotIn("—", document)
