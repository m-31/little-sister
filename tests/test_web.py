import html
import json
import os
import re
import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import Measurement

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import (
    __version__,
    csp,
    icons,
    link_probe,
    links,
    local_login,
    origins,
    secrets,
    self_report,
    slots,
    watch_lines,
)
from little_sister import app as app_module
from little_sister.checks import Check, code
from little_sister.checks.base import CheckResult, registered_types
from little_sister.config_dir import aspect_owner, forget_aspects, register_aspect
from little_sister.copy_action import copy_context
from little_sister.origins import package_origin
from little_sister.reasons import RECORD_TIMESTAMP_KEYS, Entry
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree
from little_sister.users import AvatarFile


class WebTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        # Give each test its own tree (the status route reads this global).
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def test_status_requires_login(self):
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_copy_requires_login(self):
        response = self.client.get("/copy")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_copy_renders_one_snapshot_as_markdown_and_rich_html(self):
        self._login()
        self.tree.upsert("/ci/healthy", StatusCode.OK)
        self.tree.upsert(
            "/ci/build", StatusCode.ERROR,
            "See **owner** and [run](https://ci.example/42)",
        )
        with mock.patch.object(
                self.tree, "snapshot", wraps=self.tree.snapshot) as snapshot:
            body = self.client.get("/copy").get_data(as_text=True)

        snapshot.assert_called_once_with("")
        self.assertIn("Copy Markdown", body)
        # The label names the clipboard member the button writes — `text/html`,
        # never RTF — and it reads the same on the leaf detail page, which
        # includes the same partial.
        self.assertIn("Copy Rich HTML", body)
        self.assertIn("build ⛔", body)
        self.assertNotIn("healthy", body)
        self.assertIn("<strong>owner</strong>", body)  # rendered preview
        self.assertIn('href="https://ci.example/42"', body)
        self.assertIn('id="ls-copy-source"', body)    # manual-copy fallback
        self.assertIn("js/copy.js", body)

    def test_copy_payload_cannot_break_out_of_html_or_json(self):
        self._login()
        self.tree.upsert(
            "/service/api", StatusCode.ERROR,
            "</textarea></script><script>BAD</script>",
        )

        body = self.client.get("/copy").get_data(as_text=True)

        self.assertNotIn("<script>BAD</script>", body)
        self.assertIn("&lt;script&gt;BAD&lt;/script&gt;", body)
        self.assertIn("\\u003c", body)  # tojson protects the payload boundary
        self.assertEqual(body.count('id="ls-copy-html"'), 1)

    def test_copy_empty_state_has_no_clipboard_actions(self):
        self._login()
        self.tree.upsert("/service/api", StatusCode.OK)

        body = self.client.get("/copy").get_data(as_text=True)

        self.assertIn("Nothing needs attention", body)
        self.assertNotIn("data-copy-format", body)
        self.assertNotIn("js/copy.js", body)

    def test_system_shows_version(self):
        # /system shows the package version, visible even with the engine disabled
        self._login()
        body = self.client.get("/system").get_data(as_text=True)
        self.assertIn(__version__, body)

    def test_status_renders_tree(self):
        self._login()
        self.tree.upsert("/services/web", StatusCode.OK)
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")
        response = self.client.get("/status")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("services", body)
        self.assertIn("db", body)
        self.assertIn("connection refused", body)
        self.assertIn("s-error", body)        # the db card rolled up to ERROR

    def test_node_metadata_embedded_for_popover(self):
        # ADR-0019: title/about are preloaded for the hover card, not a title= tooltip
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.set_about("/svc/api", "the billing box")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-path="/svc/api"', body)
        self.assertIn('id="node-meta"', body)
        self.assertIn("the billing box", body)             # in the embedded map

    def test_description_does_not_drive_a_card(self):
        # description stays on the leaf detail page; it is not in the popover map
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK,
                         description="The API health check")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('id="node-meta">{}<', body)   # description-only → empty map
        self.assertNotIn("The API health check", body)

    def test_popover_metadata_is_rendered_markdown(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.set_about("/svc/api", "the **billing** box")
        body = self.client.get("/status").get_data(as_text=True)
        # the map carries server-rendered HTML, escaped for the JSON/script block
        self.assertIn("\\u003cstrong\\u003ebilling", body)

    def test_node_without_metadata_absent_from_map(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)        # no title/about/description
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('id="node-meta">{}<', body)          # empty map

    def test_fragment_omits_popover_assets(self):
        # the metadata map and scripts ship with the page, not the polled fragment
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK, description="x")
        body = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn('data-path="/svc/api"', body)        # grid still tagged
        self.assertNotIn("node-meta", body)
        self.assertNotIn("inspect.js", body)

    def test_node_meta_json_escapes_script_close(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.set_about("/svc/api", "x</script><script>BAD</script>")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("<script>BAD</script>", body)     # no breakout
        self.assertIn("\\u003c", body)                     # < escaped by tojson

    def test_breadcrumbs_filter_builds_cumulative_crumbs(self):
        self.assertEqual(
            app_module._breadcrumbs("system/alpha/disk"),
            [("system", "system"), ("alpha", "system/alpha"),
             ("disk", "system/alpha/disk")])
        self.assertEqual(app_module._breadcrumbs(""), [])

    def test_breadcrumb_links_ancestors_not_current(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha/disk").get_data(as_text=True)
        self.assertIn('href="/status/system"', body)            # ancestor linked
        self.assertIn('href="/status/system/alpha"', body)     # ancestor linked
        self.assertNotIn('href="/status/system/alpha/disk"', body)  # current: plain

    def test_a_shielded_node_says_so_and_links_the_dependency(self):
        # the page of a node that is red and reaching nothing above it: without
        # this sentence an operator reads a quiet parent as good news
        self._login()
        self.tree.upsert("/net/vpn", StatusCode.ERROR)
        self.tree.upsert("/svc/api", StatusCode.ERROR, "no route to host")
        self.tree.set_dependency("/svc/api", "/net/vpn")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("Reached through", body)
        self.assertIn('href="/status/net/vpn"', body)

    def test_a_dependency_page_counts_what_is_reached_through_it(self):
        # the other end, and the risk the feature carries: one declaration can
        # quiet dozens, so the number has to be on the page that owns it
        self._login()
        self.tree.upsert("/net/vpn", StatusCode.ERROR)
        for name in ("api", "db", "queue"):
            self.tree.upsert(f"/svc/{name}", StatusCode.ERROR)
            self.tree.set_dependency(f"/svc/{name}", "/net/vpn")
        body = self.client.get("/status/net/vpn").get_data(as_text=True)
        self.assertIn("3 checks are", body)
        self.assertIn("reached through this", body)

    def test_an_ordinary_node_says_neither(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertNotIn("Reached through", body)
        self.assertNotIn("reached through this", body)

    def test_config_shown_on_detail_page(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK,
                         config="- **url:** http://example")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("Configuration", body)
        self.assertIn("http://example", body)

    def test_the_node_facts_read_when_what_was_read_found_and_ran_with(self):
        # the four cards of `_node_facts.html`, in the order its header gives them:
        # when it ran, what it read, what it found, what it ran with
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK, "200 in 412 ms",
                         config="- **url:** http://example",
                         report="- one endpoint answered",
                         subject="http://example",
                         record={"status": 200, "response_ms": 412})
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        cards = ["Time", "Measured", "Report", "Configuration"]
        headings = re.findall(
            r'<h3 class="h6 text-muted text-uppercase">([^<]+)</h3>', body)
        self.assertEqual([h for h in headings if h in cards], cards)

    def test_about_shown_on_detail_page(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.set_about("/svc/api", "the billing API box")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("the billing API box", body)

    def test_markdown_fields_rendered_on_detail_page(self):
        # about (block), reason (block) and title (inline) render to HTML (ADR-0018)
        self._login()
        self.tree.upsert("/svc/api", StatusCode.ERROR, "**down** hard")
        self.tree.set_about("/svc/api", "the *billing* box")
        self.tree.set_title("/svc/api", "`prod`")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("<strong>down</strong>", body)
        self.assertIn("<em>billing</em>", body)
        self.assertIn("<code>prod</code>", body)

    def test_a_damped_node_says_so_on_its_card_and_on_its_page(self):
        # a red leaf under a green parent is what a broken roll-up looks like, so
        # the count is on both surfaces in words (backlog #38 B)
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK, escalate_after=3)
        self.tree.upsert("/svc/api", StatusCode.ERROR)
        page = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("consecutive", page)
        self.assertIn("1 of 3", page)
        self.assertIn("still counts", page)
        card = self.client.get("/status").get_data(as_text=True)
        self.assertIn("1 of 3 to escalate", card)

    def test_an_undamped_node_says_nothing_about_escalation(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.upsert("/svc/api", StatusCode.ERROR)
        page = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertNotIn("to escalate", page)

    def test_record_shown_on_detail_page_as_dotted_names(self):
        # the record reaches the node's own page (backlog #32): a list of names
        # and values, dotted the way the field is addressed. How a time in it
        # reads is RecordTimeTests'.
        self._login()
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "CI: failed", code=StatusCode.ERROR,
                  data={"workflow": "CI", "run_number": 41,
                        "completed": {"at": "2026-09-19T09:12:00Z"}}),
        ], members=True)
        body = self.client.get("/status/ci").get_data(as_text=True)
        self.assertIn("reason-record", body)
        rows = _record_rows(body)
        self.assertEqual([name for name, _ in rows],
                         ["workflow", "run_number", "completed.at"])
        self.assertIn(("run_number", "41"), rows)

    def test_a_line_without_a_record_renders_no_record_block(self):
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        body = self.client.get("/status/db").get_data(as_text=True)
        self.assertNotIn("reason-record", body)

    def test_a_refused_record_is_said_where_the_record_would_be(self):
        # ADR-0093 decision 2: the line stands as its grading wrote it, and the
        # node's own page says in the record's place that it was refused and why —
        # escaped like any other data, since a why can quote the refused value
        self._login()
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "CI: failed", code=StatusCode.ERROR,
                  refused="it is 2,811 bytes and the limit is 2,048"),
            Entry("deploy", "deploy: passed", code=StatusCode.OK,
                  refused="'at' names a time, and '<b>x</b>' is not one with an "
                          "offset"),
            Entry("lint", "lint: passed", code=StatusCode.OK),
        ], members=True)
        body = self.client.get("/status/ci").get_data(as_text=True)
        self.assertEqual(body.count("Record refused"), 2)
        self.assertIn("it is 2,811 bytes and the limit is 2,048", body)
        self.assertNotIn("<b>x</b>", body)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", body)
        self.assertEqual(_record_rows(body), [])

    def test_record_values_are_escaped_like_any_other_data(self):
        # the escaping the check no longer has to get right itself (ADR-0018):
        # a record field is data escaped at render, not text a check interpolated
        self._login()
        self.tree.upsert("/ci", StatusCode.ERROR, [
            Entry("build", "CI: failed", code=StatusCode.ERROR,
                  data={"branch": "<script>x</script>"}),
        ], members=True)
        body = self.client.get("/status/ci").get_data(as_text=True)
        self.assertNotIn("<script>x</script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_reason_raw_html_is_escaped_in_page(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.ERROR, "<script>x</script>")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertNotIn("<script>x</script>", body)
        self.assertIn("&lt;script&gt;", body)

    # --- Observation time on the dashboard and the detail page (ADR-0027): a card
    # states *when* beside *what*, but only where "when did the check behind this node
    # run?" has exactly one answer; the detail page never invents an instant. ---

    def test_card_shows_the_observation_time_before_the_status(self):
        # The `svc` container covers exactly one check, so its card inherits that
        # check's run time — rendered as a time of day in the configured timezone
        # (ADR-0006), at minute precision (seconds saved no information worth
        # the row width), sitting directly before the cue + status word.
        self._login()
        self.tree.set_check_mount("/svc/api")
        self.tree.upsert("/svc/api", StatusCode.OK)
        stamp = self.tree.snapshot("/svc/api").timestamp
        shown = (datetime.fromisoformat(stamp).astimezone()
                 .astimezone(app_module.config.tzinfo).strftime("%H:%M"))
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn(f'<span class="status-card__time">{shown}</span>'
                      f'<svg class="status-cue', body)

    def test_card_over_two_checks_stays_bare(self):
        # Two mounts below ⇒ no single answer ⇒ the card shows nothing at all, not a
        # placeholder. The `svc` card is the only card here, so the class is absent.
        self._login()
        for path in ("/svc/api", "/svc/worker"):
            self.tree.set_check_mount(path)
            self.tree.upsert(path, StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("worker", body)                       # the card did render
        self.assertNotIn('class="status-card__time"', body)

    def test_card_without_any_mount_stays_bare(self):
        # An unwritten container with no registered mount below it (the engine-less
        # case, e.g. a nodes.yaml-only node) has nothing to show either.
        self._login()
        self.tree.set_about("/svc", "a host no check reports on")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn('class="status-card__time"', body)

    def test_detail_page_says_not_yet_observed(self):
        self._login()
        self.tree.set_about("/svc", "declared, never reported")
        body = self.client.get("/status/svc").get_data(as_text=True)
        self.assertIn("Not yet observed.", body)
        self.assertNotIn("until", body)

    def test_detail_page_shows_the_period_once_there_is_history(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("from", body)
        self.assertIn("until", body)
        self.assertNotIn("Not yet observed.", body)
        self.assertNotIn("Observed", body)

    def test_detail_page_reports_a_lone_observation_without_a_period(self):
        # A stamp but no transition of its own: report the observation rather than a
        # from/until of one instant. (An UNDEFINED write emits no event, so this is
        # the shape an inherited time would take too.)
        self._login()
        self.tree.upsert("/svc/api", StatusCode.UNDEFINED)
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("Observed", body)
        self.assertNotIn("until", body)
        self.assertNotIn("Not yet observed.", body)

    # --- Reason overflow (ADR-0024): a dashboard card clamps its reasons to a *line
    # budget* (settings.yaml reason_cap → the block's --reason-lines); the overflow
    # stays in the DOM, clipped by CSS. The show-all / collapse chevron is added
    # client-side (reasons.js), so it is exercised in the browser, not here. The
    # leaf detail page and the JSON envelope stay full. ---

    def test_reason_cap_sets_line_budget(self):
        self._login()
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [f"workflow {i} failed" for i in range(1, 9)])
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("--reason-lines: 6", body)          # the default budget
        self.assertIn('data-reason-total="8"', body)      # the block knows the total
        self.assertIn("workflow 8 failed", body)          # nothing omitted from the DOM
        self.assertNotIn("reason-extra", body)            # no per-entry cap any more
        self.assertNotIn("show all", body)                # the bottom text link is gone

    def test_reason_cap_absent_on_detail_page(self):
        # the leaf detail page keeps everything, unclamped (check.html, not the grid)
        self._login()
        self.tree.upsert("/svc/api", StatusCode.ERROR,
                         [f"line {i}" for i in range(1, 11)])
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("line 1", body)
        self.assertIn("line 10", body)                    # the tail is present
        self.assertNotIn("reason-block", body)            # no clamp machinery
        self.assertNotIn("--reason-lines", body)

    def test_reason_cap_fragment_is_well_formed(self):
        # clip by CSS only: the polled fragment never cuts rendered HTML mid-tag,
        # even with a tall code() block among many linked reasons
        self._login()
        trace = code("\n".join(f"frame {i}" for i in range(1, 60)))
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [trace] + [f"[run {i}](https://ci.example/{i}) failed"
                                    for i in range(1, 10)])   # 10 reasons total
        body = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertEqual(body.count("<pre>"), body.count("</pre>"))  # code fence closed
        self.assertEqual(body.count("<a "), body.count("</a>"))      # every link closed
        self.assertIn('data-reason-total="10"', body)
        self.assertIn("--reason-lines:", body)

    def test_reason_cap_is_configurable(self):
        # settings.yaml's reason_cap is the line budget; it reaches both the full page
        # and the ?fragment swap as the block's --reason-lines.
        self._login()
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [f"workflow {i} failed" for i in range(1, 9)])
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, reason_cap=3)):
            page = self.client.get("/status").get_data(as_text=True)
            frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        for body in (page, frag):
            self.assertIn("--reason-lines: 3", body)
            self.assertIn('data-reason-total="8"', body)
            self.assertNotIn("--reason-lines: 6", body)   # not the default

    def test_reasons_script_ships_with_page_not_fragment(self):
        # like the popover assets: the behavior loads once with the page, not on
        # every ~10s poll fragment
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        page = self.client.get("/status").get_data(as_text=True)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("js/reasons.js", page)
        self.assertNotIn("js/reasons.js", frag)

    # --- Dashboard layout (ADR-0024): the engine self-heartbeat moves out of the card
    # grid into a slim status strip, and a card's quiet (not warn/error) leaves
    # collapse to compact chips so the everyday grid holds a steadier shape. HTML
    # only — the snapshot and the JSON envelope are unchanged. ---

    def test_heartbeat_renders_in_strip_not_as_a_card(self):
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="ls-strip', body)                 # lifted into the strip
        self.assertIn('data-path="/little-sister"', body)
        self.assertIn("db", body)                    # a real card still renders
        # the heartbeat is the strip, never also a grid card
        self.assertNotIn('status-card__head" data-path="/little-sister"', body)

    def test_heartbeat_strip_ships_in_the_poll_fragment(self):
        # the strip lives inside #status-grid, so it refreshes with the ~10s poll
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        body = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("ls-strip", body)
        self.assertIn("little-sister", body)

    def test_heartbeat_strip_survives_hide_ok(self):
        # the engine pulse must stay visible even when OK nodes are hidden
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        body = self.client.get("/status?hide_ok=1").get_data(as_text=True)
        self.assertIn("ls-strip", body)
        self.assertIn("little-sister", body)

    def test_heartbeat_strip_name_links_to_its_page(self):
        # the strip name links to the heartbeat's own status page, like a card name
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="ls-strip__name"', body)
        self.assertIn('href="/status/little-sister"', body)

    def test_heartbeat_strip_carries_self_monitor_mark(self):
        # the strip gets a watching-eye glyph, marking it as the monitor
        # watching itself, set apart from the node pills.
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-strip__eye", body)

    def test_no_strip_without_a_heartbeat_node(self):
        # a branch page (or a tree with no heartbeat) shows no strip
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("ls-strip", body)

    def test_heartbeat_title_reaches_strip_and_popover_map(self):
        # The strip is a node like any other (ADR-0024): a nodes.yaml title/about on
        # the heartbeat shows in the strip and feeds the hover-card map.
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.set_title("/little-sister", "engine heartbeat")
        self.tree.set_about("/little-sister", "the pulse of the scheduler")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("engine heartbeat", body)             # title, in the strip
        self.assertIn("the pulse of the scheduler", body)   # about: only the map

    def test_the_heartbeat_branch_is_the_strip_and_its_children_are_a_page(self):
        # The heartbeat is a branch — a child per contributor (ADR-0076) — and the
        # strip is its roll-up: it summarizes the subtree the way any branch card
        # does and links to it, so lifting it hides nothing. The children are the
        # page behind the link.
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/little-sister/engine", StatusCode.OK)
        self.tree.upsert("/little-sister/state", StatusCode.WARN, "behind")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-strip s-warn", body)              # the roll-up
        self.assertNotIn('status-card__head" data-path="/little-sister"', body)
        page = self.client.get("/status/little-sister").get_data(as_text=True)
        self.assertIn("data-path=\"/little-sister/state\"", page)
        self.assertIn("behind", page)                       # nothing vanishes

    def test_quiet_leaf_renders_as_a_chip(self):
        # a card's OK leaf collapses to a compact chip (name + color); its reason,
        # if any, is a click away on the leaf page (the hover card shows title/about)
        self._login()
        self.tree.upsert("/host/cpu", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="leaf-chip s-ok"', body)
        self.assertIn('class="leaf-chip__name"', body)        # name span can ellipse
        self.assertIn('data-path="/host/cpu"', body)          # still links / inspects
        self.assertNotIn("status-node s-ok", body)            # not a full box

    def test_problem_leaf_keeps_its_box_and_reason(self):
        # a warn/error leaf stays a full box, so its reason shows at the overview
        self._login()
        self.tree.upsert("/host/disk", StatusCode.ERROR, "disk full")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("status-node s-error", body)            # a box, not a chip
        self.assertIn("disk full", body)                      # reason still visible
        self.assertNotIn("leaf-chip s-error", body)      # culprit isn't chipped

    def test_about_shown_on_branch_page(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)   # a container node
        self.tree.set_about("/system/alpha", "a NUC in the cupboard")
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn("a NUC in the cupboard", body)

    def test_title_follows_name_on_card(self):
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        self.tree.set_title("/db", "Primary database")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("db", body)                       # the name still shows
        self.assertIn("node-title", body)               # title follows it
        self.assertIn("Primary database", body)

    def test_title_in_header_on_leaf(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK, description="HTTP health check")
        self.tree.set_title("/svc/api", "Billing API")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("Billing API", body)              # title follows the breadcrumb
        self.assertIn("node-title--header", body)
        self.assertIn("HTTP health check", body)        # name + description stay below

    def test_title_shown_in_branch_header(self):
        self._login()
        self.tree.upsert("/mymble/disk", StatusCode.OK)   # a container node
        self.tree.set_title("/mymble", "Living-room NUC")
        body = self.client.get("/status/mymble").get_data(as_text=True)
        self.assertIn("Living-room NUC", body)            # follows the breadcrumb
        self.assertIn("node-title", body)

    def test_redundant_title_is_not_drawn_on_a_quiet_leaf_chip(self):
        # The case the rule exists for: a severity band whose chip reads
        # `critical Critical` (`titles.py`). The chip keeps the name.
        self._login()
        # A quiet leaf collapses to a chip only below a card, so this needs the
        # whole dashboard: `github` is the card, `severity` a box, `critical` the
        # chip inside it.
        self.tree.upsert("/github/severity/critical", StatusCode.OK)
        self.tree.set_title("/github/severity/critical", "Critical")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("leaf-chip__name", body)
        self.assertIn(">critical</span>", body)     # the name still shows
        self.assertNotIn("node-title", body)
        self.assertNotIn("Critical", body)

    def test_redundant_title_is_not_drawn_on_a_box_head_or_a_card_head(self):
        self._login()
        # A warn leaf keeps its full box rather than collapsing to a chip, and a
        # top-level node is a card head — two different lines, one rule.
        self.tree.upsert("/github/pull_requests", StatusCode.WARN, "3 open")
        self.tree.set_title("/github/pull_requests", "Pull requests")
        self.tree.set_title("/github", "The forge")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("pull_requests", body)
        self.assertIn("The forge", body)            # a real second fact survives
        self.assertNotIn("Pull requests", body)

    def test_redundant_title_is_not_drawn_in_the_page_band(self):
        self._login()
        self.tree.upsert("/github/severity/critical", StatusCode.ERROR, "one alert")
        self.tree.set_title("/github/severity/critical", "Critical")
        body = self.client.get(
            "/status/github/severity/critical").get_data(as_text=True)
        self.assertIn("critical", body)             # the breadcrumb still names it
        self.assertNotIn("node-title--header", body)
        self.assertNotIn("Critical", body)

    def test_redundant_title_leaves_a_node_out_of_the_inspection_map(self):
        # A hover card whose entire content is the word the chip already shows is
        # worse than no hover card (ADR-0019), so the node drops out of the map.
        self._login()
        self.tree.upsert("/github/severity/critical", StatusCode.OK)
        self.tree.set_title("/github/severity/critical", "Critical")
        self.tree.upsert("/github/severity/low", StatusCode.OK)
        self.tree.set_title("/github/severity/low", "Low")
        self.tree.set_about("/github/severity/low", "nothing urgent")
        meta = app_module._node_meta_map(self.tree.snapshot(""))
        self.assertNotIn("/github/severity/critical", meta)
        # `about` is untouched — only the title folded away.
        self.assertEqual(list(meta["/github/severity/low"]), ["about"])

    def test_a_glyph_title_heads_its_card_with_the_name(self):
        # ADR-0061. The card carries no name of its own, so a band titled 🔴 would
        # head a card with a bare circle — the same failure as `/copy`, in a place
        # where the chip beneath happens to soften it. One rule, both surfaces.
        self._login()
        self.tree.upsert("/github/severity/critical", StatusCode.OK)
        self.tree.set_title("/github/severity/critical", "🔴")
        self.tree.set_about("/github/severity/critical", "fix immediately")
        meta = app_module._node_meta_map(self.tree.snapshot(""))
        self.assertIn("critical 🔴", meta["/github/severity/critical"]["title"])

    def test_a_name_in_a_card_heading_is_not_read_as_markdown(self):
        # The name half is structural data and this string is rendered as Markdown
        # on its way into the card. Before this rule no name ever reached here.
        self._login()
        self.tree.upsert("/literal/*not-bold*", StatusCode.OK)
        self.tree.set_title("/literal/*not-bold*", "🔴")
        meta = app_module._node_meta_map(self.tree.snapshot(""))
        title = meta["/literal/*not-bold*"]["title"]
        self.assertIn("*not-bold*", title)
        self.assertNotIn("<em>", title)

    def test_a_word_still_heads_its_card_alone(self):
        # Unchanged, and the reason the rule is narrow: a title that says something
        # is a better heading than the name it replaces.
        self._login()
        self.tree.upsert("/services/api", StatusCode.OK)
        self.tree.set_title("/services/api", "Order intake")
        meta = app_module._node_meta_map(self.tree.snapshot(""))
        self.assertIn("Order intake", meta["/services/api"]["title"])
        self.assertNotIn("api Order intake", meta["/services/api"]["title"])

    def test_the_tree_still_carries_a_title_the_page_declines_to_draw(self):
        # The rule is display, never data (`titles.py`): the snapshot is the record
        # of what the check said, and it does not move.
        self._login()
        self.tree.upsert("/github/severity/critical", StatusCode.OK)
        self.tree.set_title("/github/severity/critical", "Critical")
        node = self.tree.snapshot("/github/severity/critical")
        self.assertEqual(node.title, "Critical")

    def test_a_declared_rank_reaches_the_dashboard(self):
        # The page renders the snapshot's child order, so ADR-0055 needs no
        # template change — this is the guard that keeps it that way.
        self._login()
        for band in ("critical", "high", "informational", "low", "medium"):
            self.tree.upsert(f"/wiz/{band}", StatusCode.OK,
                             order=1 if band == "informational" else 0)
        body = self.client.get("/status").get_data(as_text=True)
        chips = re.findall(r'leaf-chip__name">([a-z]+)<', body)
        self.assertEqual(
            chips, ["critical", "high", "low", "medium", "informational"])

    def test_branch_view(self):
        self._login()
        self.tree.upsert("/services/web", StatusCode.OK)
        response = self.client.get("/status/services")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("web", body)
        self.assertIn('href="/status"', body)        # `status` root crumb links home
        self.assertIn(">services</span>", body)      # current node, plain in the trail

    def test_missing_branch(self):
        self._login()
        response = self.client.get("/status/nope")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No such branch", response.get_data(as_text=True))

    def test_empty_tree_hint(self):
        self._login()
        response = self.client.get("/status")
        self.assertIn("No checks", response.get_data(as_text=True))

    def test_filters(self):
        self.assertEqual(app_module._status_slug(StatusCode.OK), "ok")
        self.assertEqual(app_module._status_slug(StatusCode.ERROR), "error")
        self.assertEqual(app_module._shorten("abcdef", 3), "ab…")
        self.assertEqual(app_module._shorten("abc", 10), "abc")

    def test_shorten_never_cuts_through_a_markdown_link(self):
        # The clamp is applied *before* `markdown` on the dashboard card, so a cut
        # landing inside `[label](url)` used to leave the raw syntax and half a URL
        # on the page — longer than the text it replaced, and unreadable.
        line = "waiting: [#4821](https://forge.example.org/andro-meda/pulls/4821) ok"
        for length in range(12, len(line)):
            with self.subTest(length=length):
                cut = app_module._shorten(line, length)
                self.assertNotIn("](", cut.rstrip("…").rsplit(")", 1)[-1],
                                 f"{cut!r} ends inside a link")

    def test_shorten_keeps_a_link_whole_rather_than_losing_it(self):
        # When the link starts before anything else fits, overshooting the budget is
        # the right trade: a link's *source* is long and what a reader sees is its
        # label, so keeping it costs almost no rendered width — and dropping it costs
        # the whole reason.
        line = "[#4821](https://forge.example.org/andro-meda/pulls/4821) and more"
        cut = app_module._shorten(line, 20)
        self.assertTrue(cut.startswith("[#4821](https://"), cut)
        self.assertIn(")", cut)

    def test_shorten_leaves_link_free_text_exactly_as_before(self):
        # every other caller (the popover's note, which is never rendered as
        # Markdown) must be untouched by the link rule
        plain = "a" * 300
        self.assertEqual(app_module._shorten(plain, 100), "a" * 99 + "…")

    def test_hide_ok_filter(self):
        self._login()
        self.tree.upsert("/alpha", StatusCode.OK)
        self.tree.upsert("/omega", StatusCode.ERROR, "boom")
        body = self.client.get("/status?hide_ok=1").get_data(as_text=True)
        self.assertNotIn("alpha", body)   # OK card hidden
        self.assertIn("omega", body)      # ERROR card shown

    def test_depth_limits_tree_and_persists(self):
        self._login()
        self.tree.upsert("/sys/host/svc/leaf", StatusCode.ERROR, "boom")
        # the default renders the full depth
        self.assertIn("boom", self.client.get("/status").get_data(as_text=True))
        # depth counts levels below the root: depth=3 reaches svc but not the
        # leaf beneath it, and the choice is saved in a cookie
        response = self.client.get("/status?depth=3")
        body = response.get_data(as_text=True)
        self.assertIn("svc", body)
        self.assertNotIn("boom", body)
        self.assertIn("depth=3", response.headers.get("Set-Cookie", ""))
        # the saved cookie is honored on a later plain request
        self.assertNotIn(
            "boom", self.client.get("/status").get_data(as_text=True))

    def test_leaf_density_off_renders_boxes(self):
        # the density switch off (a form submit — the `view` marker — with
        # the chips box unchecked, so no `dense`) spells quiet leaves out as boxes
        self._login()
        self.tree.upsert("/host/cpu", StatusCode.OK)
        body = self.client.get("/status?view=1").get_data(as_text=True)
        self.assertNotIn("leaf-chip", body)              # no chip
        self.assertIn("status-node s-ok", body)          # a full box instead
        self.assertIn("cpu", body)

    def test_leaf_density_reaches_the_fragment(self):
        # the flag drives the ?fragment swap too, not just the full page
        self._login()
        self.tree.upsert("/host/cpu", StatusCode.OK)
        self.assertIn(
            "leaf-chip", self.client.get("/status?fragment=1").get_data(as_text=True))
        self.assertNotIn(
            "leaf-chip",
            self.client.get("/status?view=1&fragment=1").get_data(as_text=True))

    def _branchy_card(self):
        # a card ('nas') whose sub-branches are all-OK boxes (each holds an OK leaf) —
        # the branch-density skyscraper — plus one erupting sub-branch (ADR-0024).
        for aspect in ("alpha", "beta", "gamma", "delta", "epsilon"):
            self.tree.upsert(f"/nas/{aspect}/probe", StatusCode.OK)
        self.tree.upsert("/nas/zeta/probe", StatusCode.ERROR, "zeta down")

    def test_branch_density_caps_quiet_boxes(self):
        # dense view: a branch shows branch_cap quiet sub-branch boxes and folds the
        # rest behind a "+N more" (cap 3, five quiet aspects → two folded)
        self._login()
        self._branchy_card()
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, branch_cap=3)):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count("is-extra"), 2)          # 5 quiet − cap 3
        self.assertIn('class="branch-more"', body)
        self.assertIn("+2 more", body)

    def test_branch_density_never_folds_a_problem_box(self):
        # nothing urgent hides: even at cap 0 (every quiet box folds) the erupting
        # sub-branch keeps its box and reason, and never counts toward the cap
        self._login()
        self._branchy_card()
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, branch_cap=0)):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count("is-extra"), 5)      # the five quiet, not zeta
        self.assertIn("zeta down", body)                 # the culprit's reason shows
        self.assertIn("+5 more", body)

    def test_branch_density_off_spells_everything_out(self):
        # density off (the `view` marker, chips unchecked) → no cap, no control
        self._login()
        self._branchy_card()
        body = self.client.get("/status?view=1").get_data(as_text=True)
        self.assertNotIn("is-extra", body)
        self.assertNotIn("branch-more", body)

    def test_branch_cap_reaches_the_fragment(self):
        # the cap drives the ~10s ?fragment swap too, not just the full page
        self._login()
        self._branchy_card()
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, branch_cap=3)):
            frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn('class="branch-more"', frag)
        self.assertIn("+2 more", frag)

    # --- a node that declines the density trade (ADR-0063) ---

    _INVENTORY = "12 instances, oldest 41 days"

    @staticmethod
    def _box_classes(body, path):
        """The classes on the rendered box whose head is ``path`` — so a fold
        assertion names the node it is about rather than counting substrings."""
        match = re.search(
            r'<div class="(status-node[^"]*)">\s*'
            r'<div class="status-node__self" data-path="' + re.escape(path) + '"',
            body)
        assert match is not None, f"no box rendered for {path}"
        return match.group(1)

    def _declared_inventory(self):
        """A card ('aws') whose quiet `ec2` leaf declares that its lines are still
        information, beside quiet siblings that do not."""
        self.tree.upsert("/aws/ec2", StatusCode.OK, [self._INVENTORY],
                         show_when_quiet=True)
        for aspect in ("batch", "cloudwatch", "iam"):
            self.tree.upsert(f"/aws/{aspect}", StatusCode.OK)

    def test_a_declared_quiet_leaf_keeps_its_box_while_its_siblings_chip(self):
        # The claim itself: an inventory's lines are read *because* everything is
        # fine, so a density mechanism must not trade them away for being quiet.
        self._login()
        self._declared_inventory()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn(self._INVENTORY, body)                    # its lines show
        self.assertIn("status-node s-ok", self._box_classes(body, "/aws/ec2"))
        self.assertEqual(body.count('class="leaf-chip s-ok"'), 3)   # the siblings

    def test_saying_nothing_paints_exactly_as_before(self):
        # The safety of the mechanism: an undeclared quiet leaf still chips, and
        # its reason is a click away as it always was.
        self._login()
        self.tree.upsert("/aws/ec2", StatusCode.OK, [self._INVENTORY])
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="leaf-chip s-ok"', body)
        self.assertNotIn(self._INVENTORY, body)

    def test_a_declared_false_paints_exactly_as_before(self):
        # The deployment's way of declining a claim the check type ships: `false`
        # is a statement in the tree and today's painting on the screen.
        self._login()
        self.tree.upsert("/aws/ec2", StatusCode.OK, [self._INVENTORY],
                         show_when_quiet=False)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="leaf-chip s-ok"', body)
        self.assertNotIn(self._INVENTORY, body)

    def test_the_declaration_closes_the_chip_run_around_itself(self):
        # The chip-run wrapper has to agree with the chip condition about the
        # neighbors, or a declared node between two chips leaves the run's <span>
        # open and every chip after it lands inside the wrong wrapper.
        self._login()
        self.tree.upsert("/aws/alpha", StatusCode.OK)
        self.tree.upsert("/aws/mid", StatusCode.OK, show_when_quiet=True)
        self.tree.upsert("/aws/zulu", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('<span class="leaf-chip-run">'), 2)
        self.assertEqual(body.count("</span>\n    \n"), 0)   # no stray open run
        squashed = re.sub(r"\s+", "", body)
        # run(alpha) closes, the declared box follows, then run(zulu) opens
        self.assertRegex(
            squashed,
            r'<spanclass="leaf-chip-run"><aclass="leaf-chip[^>]*?'
            r'data-path="/aws/alpha".*?</a></span><divclass="status-node')
        self.assertRegex(
            squashed,
            r'</div></div><spanclass="leaf-chip-run"><aclass="leaf-chip[^>]*?'
            r'data-path="/aws/zulu"')

    def test_a_declared_box_is_never_folded_behind_more(self):
        # Exemption from one compaction and not the other would hide *more* than
        # the chip did, so a declared node is not counted a surplus quiet box.
        self._login()
        self._branchy_card()                       # five quiet, one erupting
        self.tree.upsert("/nas/inventory/probe", StatusCode.OK)
        self.tree.set_show_when_quiet("/nas/inventory", True)
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, branch_cap=3)):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("is-extra", self._box_classes(body, "/nas/inventory"))
        # …and it does not spend a quiet sibling's place in the cap either: still
        # five foldable boxes against cap 3, exactly as without it
        self.assertEqual(body.count("is-extra"), 2)
        self.assertIn("+2 more", body)

    def test_a_declared_box_survives_a_cap_of_zero(self):
        # The same exemption a warn/error box has: at cap 0 every foldable box
        # folds and the declared one still does not.
        self._login()
        self._branchy_card()
        self.tree.upsert("/nas/inventory/probe", StatusCode.OK)
        self.tree.set_show_when_quiet("/nas/inventory", True)
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, branch_cap=0)):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("is-extra", self._box_classes(body, "/nas/inventory"))
        self.assertEqual(body.count("is-extra"), 5)
        self.assertIn("+5 more", body)

    def test_density_off_is_untouched_by_the_declaration(self):
        # With density off every node is a full box already, so the field does
        # nothing — and nothing about the wall changes for declaring one.
        self._login()
        self._declared_inventory()
        body = self.client.get("/status?view=1").get_data(as_text=True)
        self.assertNotIn("leaf-chip", body)
        self.assertIn(self._INVENTORY, body)

    def test_a_declared_node_is_still_hidden_when_the_viewer_hides_ok(self):
        # Not an exemption from the viewer's filters (ADR-0063): a declared node
        # is still OK, and "problems only" is the person at the screen speaking.
        self._login()
        self._declared_inventory()
        self.tree.upsert("/aws/batch", StatusCode.ERROR, "queue stuck")
        body = self.client.get("/status?hide_ok=1").get_data(as_text=True)
        self.assertIn("queue stuck", body)
        self.assertNotIn(self._INVENTORY, body)

    def test_a_declared_node_that_never_reported_is_still_idle(self):
        # The same rule from the other side: declaring it does not make a node
        # that has never reported anything worth showing under *hide idle*.
        self._login()
        self.tree.upsert("/aws/batch", StatusCode.OK)
        self.tree.set_show_when_quiet("/aws/ec2", True)   # auto-created, unwritten
        plain = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-path="/aws/ec2"', plain)
        hidden = self.client.get("/status?hide_idle=1").get_data(as_text=True)
        self.assertNotIn('data-path="/aws/ec2"', hidden)

    def test_the_declaration_reaches_the_fragment(self):
        # It has to survive the ~10s poll swap, like the cap and the density flag.
        self._login()
        self._declared_inventory()
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn(self._INVENTORY, frag)

    def test_branches_script_ships_with_page_not_fragment(self):
        # like reasons.js / the popover assets: the behavior loads once with the page,
        # not on every ~10s poll fragment
        self._login()
        self._branchy_card()
        page = self.client.get("/status").get_data(as_text=True)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("js/branches.js", page)
        self.assertNotIn("js/branches.js", frag)

    def test_dashboard_layout_script_ships_with_page_not_fragment(self):
        self._login()
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        page = self.client.get("/status").get_data(as_text=True)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("js/dashboard-layout.js", page)
        self.assertNotIn("js/dashboard-layout.js", frag)
        self.assertIn("data-layout-breakpoints", page)
        # `/quality/github/actions` is a three-node chain: three visible nodes
        # cost three stable rows, but nothing branches, so its only useful step
        # is the ordinary one-track width.
        self.assertIn('data-layout-weight="3"', page)
        self.assertIn('data-layout-steps="1"', page)
        self.assertIn("[[1, 0, [1]]]", page)

    def test_plain_dashboard_columns_withholds_the_span_plan(self):
        # settings.yaml `dashboard_columns: plain` (ADR-0056): the page keeps
        # the ordinary auto-fill grid — no breakpoints, no per-card layout
        # data — which is exactly the no-JavaScript rendering. The script may
        # still ship; with nothing to read it clears spans and stands down.
        self._login()
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        patched = replace(app_module.config, dashboard_columns="plain")
        with mock.patch.object(app_module, "config", patched):
            page = self.client.get("/status").get_data(as_text=True)
            frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertNotIn("data-layout-breakpoints", page)
        self.assertNotIn("data-layout-weight", page)
        self.assertNotIn("data-layout-steps", page)
        self.assertNotIn("data-layout-breakpoints", frag)
        self.assertIn('class="status-grid"', page)

    def test_status_cue_marks_state_not_color_alone(self):
        # a11y: a per-state shape cue gives a non-color channel; it is decorative
        # (aria-hidden), the status word stays for screen readers
        self._login()
        self.tree.upsert("/web", StatusCode.OK)
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("status-cue--ok", body)
        self.assertIn("status-cue--error", body)
        self.assertIn('aria-hidden="true"', body)

    def test_status_cue_on_a_problem_node_box(self):
        # a warn/error leaf is a color-only box with no status word — it gets a cue
        # too (the host card rolls up to WARN, so two warn cues: the card and the box)
        self._login()
        self.tree.upsert("/host/disk", StatusCode.WARN, "SMART pending")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count("status-cue--warn"), 2)

    def test_status_cue_not_on_quiet_chips(self):
        # chips are only ever quiet leaves and stay uncued; the card still cues, so a
        # lone OK leaf yields exactly one cue (the card's, not the chip's)
        self._login()
        self.tree.upsert("/host/cpu", StatusCode.OK)   # dense → a chip
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("leaf-chip", body)
        self.assertEqual(body.count("status-cue--"), 1)

    def test_status_cue_on_the_strip(self):
        # the self-monitor strip carries a state cue like the cards
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/web", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-strip", body)
        self.assertEqual(body.count("status-cue--"), 2)   # strip + web card

    def test_node_box_word_speaks_and_its_cue_stays_decorative(self):
        # DELIBERATELY REWRITTEN with the box state cluster: a box now prints
        # its status word like a card does, so the visible word is the
        # accessible channel (WCAG 1.1.1) and the cue drops its role=img — a
        # named cue beside a word would double-announce. Coded reason lines
        # keep their labeled cues; this scenario has none.
        self._login()
        self.tree.upsert("/host/disk", StatusCode.ERROR, "disk full")
        body = self.client.get("/status").get_data(as_text=True)
        clusters = re.findall(r'status-node__state">.*?</button></span>', body)
        self.assertTrue(any("error<button" in c for c in clusters))  # the word speaks
        self.assertNotIn('role="img"', body)        # ...so no cue is named

    def test_quiet_node_box_cue_not_announced(self):
        # every box cue is decorative now that the word speaks; a quiet box in
        # particular must not have a reader hear a stream of "ok"s
        self._login()
        self.tree.upsert("/host/disk/smart", StatusCode.OK)  # /host/disk = quiet box
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("status-node__self", body)   # /host/disk renders as a box
        self.assertNotIn('role="img"', body)       # no box announces (all quiet)

    def test_card_and_strip_cues_stay_aria_hidden(self):
        # a card/strip cue stays decorative — the status word beside it already speaks,
        # so a named cue would double-announce
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-strip", body)
        self.assertNotIn('role="img"', body)   # no boxes → every cue hidden

    def test_maintenance_pill_lists_a_deep_pin(self):
        # the strip pill's whole-set popover surfaces every pin regardless of
        # depth — a pin the roll-up hides at a shallow depth is still listed in full
        self._login()
        self.tree.set_maintenance(
            "/rack/shelf/box", "planned",
            expires_at=datetime.now() + timedelta(hours=5), set_by="pan")
        body = self.client.get("/status?depth=1").get_data(as_text=True)
        self.assertIn("maintenance-pill", body)
        # the __all__ popover source carries the full path, though depth 1 hides it
        frag = body.split('data-pop-for="__all__"', 1)[1].split("</template>", 1)[0]
        self.assertIn("/rack/shelf/box", frag)

    def test_maintenance_pill_survives_hide_idle(self):
        # the pill and its popover are built from the unfiltered snapshot, so hide-idle
        # can't hide them
        self._login()
        self.tree.set_maintenance(
            "/db", "planned",
            expires_at=datetime.now() + timedelta(days=2), set_by="pan")
        body = self.client.get("/status?hide_idle=1").get_data(as_text=True)
        self.assertIn("maintenance-pill", body)
        self.assertIn("/db", body)

    def test_hide_idle_keeps_maintenance_but_hides_undefined(self):
        # hide-idle hides only never-reported (UNDEFINED); maintenance is
        # an intentional admin state and stays in the grid
        self._login()
        self.tree.set_maintenance(
            "/planned-host", "kernel",
            expires_at=datetime.now() + timedelta(days=1), set_by="pan")
        self.tree.set_about("/idle-host", "provisioned, not reporting yet")  # UNDEFINED
        self.tree.upsert("/web", StatusCode.OK)
        body = self.client.get("/status?hide_idle=1").get_data(as_text=True)
        self.assertIn("planned-host", body)      # maintenance card stays visible
        self.assertNotIn("idle-host", body)      # never-reported card hidden

    def test_maintenance_pip_on_ancestor_card(self):
        # a card whose subtree holds a pin (but isn't itself pinned) gets a clickable
        # pip button (maintenance.js opens its popover); a glance shows where to drill
        self._login()
        self.tree.set_maintenance(
            "/rack/shelf/box", "planned",
            expires_at=datetime.now() + timedelta(hours=3), set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("maintenance-pip", body)
        self.assertIn('aria-haspopup="true"', body)   # the pip opens a popover
        self.assertIn('data-pop-for="/rack"', body)    # keyed to the card

    def test_maintenance_pip_popover_is_scoped_to_its_card(self):
        # each pip's popover source lists only that card's pins, not another card's
        self._login()
        self.tree.set_maintenance(
            "/rack/a/x", "swap",
            expires_at=datetime.now() + timedelta(hours=2), set_by="pan")
        self.tree.set_maintenance(
            "/other/b/y", "swap",
            expires_at=datetime.now() + timedelta(hours=2), set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        frag = body.split('data-pop-for="/rack"', 1)[1].split("</template>", 1)[0]
        self.assertIn("/rack/a/x", frag)         # /rack's own pin is in its popover
        self.assertNotIn("/other/b/y", frag)     # another card's pin is not

    def test_no_maintenance_surfaces_without_pins(self):
        self._login()
        self.tree.upsert("/web", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("maintenance-pill", body)   # no strip pill without pins
        self.assertNotIn("maintenance-pip", body)

    def test_maintenance_pill_shows_count(self):
        # the pill wears a live count of pinned nodes ("N in maintenance")
        self._login()
        for path in ("/db", "/rack/shelf/box", "/web/api"):
            self.tree.set_maintenance(
                path, "planned",
                expires_at=datetime.now() + timedelta(hours=4), set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("maintenance-pill", body)
        self.assertIn('maintenance-pill__count">3<', body)   # live count of pins
        self.assertIn("in maintenance", body)

    def test_maintenance_pill_is_a_link_to_the_page(self):
        # the pill is a link to /maintenance, so no-JS still reaches the page; JS
        # upgrades that click to the popover instead
        self._login()
        self.tree.set_maintenance(
            "/db", "planned",
            expires_at=datetime.now() + timedelta(hours=2), set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        tag = body.split('<a class="maintenance-pill"', 1)[1].split(">", 1)[0]
        self.assertIn('href="/maintenance"', tag)   # the pill itself links to the page

    def test_maintenance_popover_caps_with_more_link(self):
        # the pill popover shows the first maintenance_cap pins, then a
        # "+N more" link to the full /maintenance page (the leaf-detail pattern)
        self._login()
        for i in range(5):
            self.tree.set_maintenance(
                f"/host{i}/box", "planned",
                expires_at=datetime.now() + timedelta(hours=2), set_by="pan")
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, maintenance_cap=2)):
            body = self.client.get("/status").get_data(as_text=True)
        frag = body.split('data-pop-for="__all__"', 1)[1].split("</template>", 1)[0]
        # exactly the cap of pins are listed inline, the rest fold into "+3 more"
        self.assertEqual(frag.count("maintenance-pop__item"), 2)
        self.assertIn("+3 more", frag)
        self.assertIn('href="/maintenance"', frag)

    def test_maintenance_page_lists_all_pins_uncapped(self):
        # the /maintenance page renders the full overview, past the popover's cap
        self._login()
        for i in range(5):
            self.tree.set_maintenance(
                f"/host{i}/box", "planned",
                expires_at=datetime.now() + timedelta(hours=2), set_by="pan")
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, maintenance_cap=2)):
            body = self.client.get("/maintenance").get_data(as_text=True)
        for i in range(5):
            self.assertIn(f"/host{i}/box", body)   # every pin, not just the first two

    def test_maintenance_page_requires_login(self):
        # a read-only page behind the same auth gate as /status
        response = self.client.get("/maintenance")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_humanize_remaining(self):
        # the index's coarse 'time left' picks the largest one or two units
        h = app_module._humanize_remaining
        self.assertEqual(h(90000), "1d 1h")
        self.assertEqual(h(86400), "1d")
        self.assertEqual(h(5400), "1h 30m")
        self.assertEqual(h(3600), "1h")
        self.assertEqual(h(300), "5m")
        self.assertEqual(h(30), "< 1m")
        self.assertEqual(h(0), "expired")
        self.assertEqual(h(-10), "expired")

    def test_density_off_persists_via_cookie(self):
        # the density switch persists like depth — set on an explicit
        # change (SameSite=Lax), honored on a later plain visit
        self._login()
        self.tree.upsert("/host/cpu", StatusCode.OK)   # quiet leaf, chip by default
        first = self.client.get("/status?view=1")        # chips unchecked
        self.assertIn("SameSite=Lax", first.headers.get("Set-Cookie", ""))
        body = self.client.get("/status").get_data(as_text=True)   # later plain visit
        self.assertNotIn("leaf-chip", body)              # density-off remembered
        self.assertIn("status-node s-ok", body)

    def test_hide_ok_persists_via_cookie(self):
        # hide-ok persists across visits, like depth
        self._login()
        self.tree.upsert("/database", StatusCode.OK)
        self.tree.upsert("/webserver", StatusCode.ERROR, "500")
        self.client.get("/status?view=1&hide_ok=1")      # explicit change → cookie
        body = self.client.get("/status").get_data(as_text=True)   # later plain visit
        self.assertNotIn("database", body)               # OK card stays hidden
        self.assertIn("webserver", body)

    def test_depth_zero_shows_single_overall_card(self):
        self._login()
        self.tree.upsert("/sys/host/check", StatusCode.ERROR, "down")
        body = self.client.get("/status?depth=0").get_data(as_text=True)
        # depth 0 collapses the whole tree to one rolled-up "overall" card
        self.assertIn("overall", body)
        # it shows the rolled-up color and stays bold (it carries the status)
        self.assertIn('status-card s-error"', body)
        # nothing below the root is rendered
        self.assertNotIn("status-node s-", body)
        self.assertNotIn("status-node__reason", body)
        # ...nor the reason's text. Matched with its tags: a bare "down" also
        # occurs inside Bootstrap's "dropdown" classes in the settings menu.
        self.assertNotIn(">down<", body)

    def test_derived_status_dimmed_culprit_bold(self):
        self._login()
        self.tree.upsert("/sys/host/check", StatusCode.ERROR, "down")
        body = self.client.get("/status").get_data(as_text=True)
        # host is red only because of its child → dimmed
        self.assertIn('status-node s-error dim"', body)
        # the leaf check reports the error itself → bold (not dimmed)
        self.assertIn('status-node s-error"', body)

    def test_leaf_detail_page(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK, "all good",
                         description="The API health check", frequency_seconds=300)
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("The API health check", body)
        self.assertIn("Status:", body)
        self.assertIn("History", body)
        self.assertIn("Set maintenance", body)   # pan is an admin

    def test_history_page(self):
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        body = self.client.get("/history/db").get_data(as_text=True)
        self.assertIn("Since", body)
        self.assertIn("Until", body)
        self.assertIn("error", body)

    def test_a_container_that_declares_nothing_has_no_current_history_row(self):
        # ADR-0094 decision 5, the Time card's rule: a node that declares nothing above
        # nodes that report has no own status for a period to name, so its history
        # ends with the last period that named one, and says since when
        self._login()
        self.tree.upsert("/aws/account", StatusCode.OK, "scope: 1 account")
        self.tree.upsert("/aws/account/eu", StatusCode.OK)
        self.tree.upsert("/aws/account", StatusCode.UNDEFINED, "scope: 1 account")
        body = self.client.get("/history/aws/account").get_data(as_text=True)
        rows = body.split("<tbody>")[1].split("</tbody>")[0]
        self.assertEqual(rows.count("<tr"), 1)
        self.assertIn(">ok<", rows)
        self.assertNotIn(">undefined<", rows)
        self.assertIn("Declares nothing of its own since", body)

    def test_a_leaf_keeps_its_undefined_history_row(self):
        # a leaf's UNDEFINED is its own reading, as on its Time card
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        self.tree.upsert("/db", StatusCode.UNDEFINED, "no data")
        body = self.client.get("/history/db").get_data(as_text=True)
        rows = body.split("<tbody>")[1].split("</tbody>")[0]
        self.assertEqual(rows.count("<tr"), 2)
        self.assertIn(">undefined<", rows)
        self.assertNotIn("Declares nothing of its own", body)

    def test_events_page(self):
        self._login()
        self.tree.upsert("/jenkins/security", StatusCode.ERROR, "CBP failed")
        body = self.client.get("/events").get_data(as_text=True)
        self.assertIn("jenkins/security", body)
        self.assertIn("CBP failed", body)

    def test_maintenance_admin(self):
        self._login()   # pan is an admin
        self.tree.upsert("/db", StatusCode.OK)
        response = self.client.post(
            "/maintenance",
            data={"path": "db", "action": "set", "reason": "planned"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.tree.effective("/db"), StatusCode.MAINTENANCE)

    def test_maintenance_records_who_and_when(self):
        self._login()   # pan is an admin
        self.tree.upsert("/db", StatusCode.OK)
        self.client.post("/maintenance",
                         data={"path": "db", "action": "set",
                               "reason": "planned", "duration": "2h"})
        body = self.client.get("/status/db").get_data(as_text=True)
        self.assertIn("in maintenance", body)
        self.assertIn("Pinned by", body)
        self.assertIn("pan", body)          # created_by = the session user
        self.assertIn("Expires", body)
        # an untouched pin says nothing about a last change (ADR-0014)
        self.assertNotIn("Last changed by", body)

    def test_maintenance_blocks_non_admin(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        response = self.client.post("/maintenance",
                                    data={"path": "db", "action": "set"})
        self.assertEqual(response.status_code, 403)

    def _page(self, url: str) -> str:
        return self.client.get(url).get_data(as_text=True)

    def test_a_self_report_action_runs_for_an_admin_and_comes_back_with_its_word(self):
        """ADR-0076: a package's action on its contributor's node — a POST, admin
        only, answered on the page it came back to."""
        self_report.forget_actions()
        self.addCleanup(self_report.forget_actions)
        ran: list[str] = []

        def take_over() -> str:
            ran.append("took")
            return "took the lease over"

        self_report.register_action("aws-keeper", "take-over", "Take over", take_over)
        self._login()   # pan is an admin
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/little-sister/aws-keeper", StatusCode.OK)
        # the button, on the contributor's node, for an admin
        page = self._page("/status/little-sister/aws-keeper")
        self.assertIn('action="/little-sister/aws-keeper/act/take-over"', page)
        self.assertIn(">Take over<", page)

        response = self.client.post("/little-sister/aws-keeper/act/take-over")

        self.assertEqual(ran, ["took"])
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(
            "/status/little-sister/aws-keeper"))
        page = self._page("/status/little-sister/aws-keeper")
        self.assertIn("took the lease over", page)

    def test_an_action_that_ran_is_followed_by_a_flush_of_the_state_layer(self):
        """ADR-0076 decision 6: what an action changed reaches the store now — the
        kept files written and the keeper given its tick — not at the next
        interval; a handler that raised is not followed by one."""
        import tempfile

        from little_sister.state import StateLayer
        self_report.forget_actions()
        self.addCleanup(self_report.forget_actions)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            held = {"pins": []}
            state.keep("kept.json", lambda: held)
            state.tick()                          # the interval starts; nothing written
            app_module.state_layer = state
            self.addCleanup(setattr, app_module, "state_layer", None)

            def take_over() -> str:
                held["pins"] = ["/db"]
                return "took the lease"

            def broken() -> str:
                held["pins"] = ["/never"]
                raise RuntimeError("bucket unreachable")
            self_report.register_action("aws-keeper", "take-over", "Take over",
                                        take_over)
            self_report.register_action("aws-keeper", "release", "Release", broken)
            self._login()
            self.assertFalse(state.path("kept.json").exists())

            self.client.post("/little-sister/aws-keeper/act/take-over")

            self.assertEqual(json.loads(state.path("kept.json").read_text()),
                             {"pins": ["/db"]})
            with self.assertLogs("little_sister", level="ERROR"):
                self.client.post("/little-sister/aws-keeper/act/release")
            self.assertEqual(json.loads(state.path("kept.json").read_text()),
                             {"pins": ["/db"]}, "no flush behind a handler that raised")

    def test_a_self_report_action_that_raises_is_its_own_sentence(self):
        self_report.forget_actions()
        self.addCleanup(self_report.forget_actions)

        def broken() -> str:
            raise RuntimeError("bucket unreachable")

        self_report.register_action("aws-keeper", "release", "Release", broken)
        self._login()
        with self.assertLogs("little_sister", level="ERROR"):
            response = self.client.post("/little-sister/aws-keeper/act/release")
        self.assertEqual(response.status_code, 302)
        page = self._page("/status/little-sister/aws-keeper")
        self.assertIn("Release failed", page)
        self.assertIn("bucket unreachable", page)

    def test_a_self_report_action_is_admin_only_and_unknown_is_404(self):
        self_report.forget_actions()
        self.addCleanup(self_report.forget_actions)
        self_report.register_action("aws-keeper", "take-over", "Take over",
                                    lambda: "no")
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        self.assertEqual(
            self.client.post("/little-sister/aws-keeper/act/take-over").status_code,
            403)
        # and the button is not offered to a viewer either
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/little-sister/aws-keeper", StatusCode.OK)
        page = self._page("/status/little-sister/aws-keeper")
        self.assertNotIn("/act/take-over", page)
        self._login()
        self.assertEqual(
            self.client.post("/little-sister/aws-keeper/act/nothing").status_code,
            404)

    def test_take_the_backups_is_the_state_childs_action(self):
        """ADR-0077: the library's own action, registered where the layer is —
        admin-only, answered on the child's page with what was taken."""
        from little_sister.state import BACKUP_SUFFIX, MAINTENANCE_FILE, StateLayer
        self_report.forget_actions()
        self.addCleanup(self_report.forget_actions)

        class _Roots:
            def check_roots(self) -> list[str]:
                return ["/db"]
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            far = datetime.now() + timedelta(days=1)
            # what an earlier process set aside: a pin on /db this one lacks
            state.path(MAINTENANCE_FILE + BACKUP_SUFFIX).write_text(json.dumps({
                "nodes": {"/db": {"reason": "from the backup",
                                  "set_at": "2026-01-01T00:00:00",
                                  "expires_at": far.isoformat(),
                                  "set_by": "ada"}},
                "entries": {}}))
            app_module._restore_state(_Roots(), state)  # type: ignore[arg-type]
            self._login()   # pan is an admin
            self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
            self.tree.upsert("/little-sister/state", StatusCode.OK)
            page = self._page("/status/little-sister/state")
            self.assertIn('action="/little-sister/state/act/take-backups"', page)
            self.assertIn(">Take the backups<", page)
            self.assertIsNone(self.tree.maintenance_entry("/db"))

            response = self.client.post("/little-sister/state/act/take-backups")

            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.tree.maintenance_entry("/db").reason,
                             "from the backup")
            page = self._page("/status/little-sister/state")
            self.assertIn("took the backup of maintenance.json", page)

    def test_system_page_admin(self):
        self._login()   # pan is an admin
        app_module.engine = None
        response = self.client.get("/system")
        self.assertEqual(response.status_code, 200)
        self.assertIn("System", response.get_data(as_text=True))

    def test_system_blocks_non_admin(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        self.assertEqual(self.client.get("/system").status_code, 403)

    def test_status_fragment_returns_grid_only(self):
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        body = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("status-grid", body)
        self.assertNotIn("<!DOCTYPE", body)
        self.assertNotIn("<nav", body)

    def test_status_page_has_poller(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("js/poll.js", body)
        self.assertIn('data-target="status-grid"', body)

    def test_system_page_has_poller_and_stamp(self):
        # /system never navigates on its own, so it dates its info (with the
        # configured full format — date included) and polls like the dashboard
        self._login()
        app_module.engine = None
        body = self.client.get("/system").get_data(as_text=True)
        self.assertIn("js/poll.js", body)
        self.assertIn('data-target="system-info"', body)
        self.assertRegex(
            body, r'data-rendered-at="\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"')
        self.assertRegex(body, r'updated \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')

    def test_system_fragment_returns_info_only(self):
        self._login()
        app_module.engine = None
        response = self.client.get("/system?fragment=1")
        body = response.get_data(as_text=True)
        self.assertIn("engine is not running", body)
        self.assertNotIn("<!DOCTYPE", body)
        self.assertNotIn("<nav", body)
        # the poll reads the same server-formatted stamp as the dashboard's
        self.assertIsNotNone(response.headers.get("X-Rendered-At"))

    def test_poll_js_treats_headerless_response_as_failure(self):
        # a fragment fetch that lands on the login page (expired session) has
        # no X-Rendered-At; the poll must fail it, never swap it in
        js = self.client.get("/static/js/poll.js").get_data(as_text=True)
        self.assertIn("X-Rendered-At", js)
        self.assertIn("!r.ok || !renderedAt", js)

    def test_poll_js_swaps_muted_for_danger_on_failure(self):
        # both .text-muted and .text-danger are !important in Bootstrap and
        # muted comes later in the stylesheet — stacking them renders gray, so
        # the failure path must remove muted for the red to actually show
        js = self.client.get("/static/js/poll.js").get_data(as_text=True)
        self.assertIn("classList.remove('text-muted')", js)
        self.assertIn("classList.add('text-danger')", js)

    def test_poll_js_escalates_a_sustained_outage(self):
        # ADR-0005: six consecutive misses escalate to a banner,
        # dimmed content and a tab-title prefix; session expiry escalates
        # immediately; a woken tab re-polls at once
        js = self.client.get("/static/js/poll.js").get_data(as_text=True)
        self.assertIn("ESCALATE_AFTER = 6", js)
        self.assertIn("poll-stale", js)
        self.assertIn("'(stale) '", js)
        self.assertIn("Session expired", js)
        self.assertIn("visibilitychange", js)
        # the dim class exists in the stylesheet the pages actually load
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        self.assertIn(".poll-stale", css)

    def test_engine_error_banner_on_pages(self):
        # a failed engine start reaches every page's header
        self._login()
        with mock.patch.object(app_module, "engine_error",
                               "checks/web.yaml: unknown check type 'htttp'"):
            for page in ("/status", "/events", "/system"):
                with self.subTest(page=page):
                    body = self.client.get(page).get_data(as_text=True)
                    self.assertIn("Engine not started", body)
                    self.assertIn("unknown check type", body)

    def test_no_banner_when_engine_ok(self):
        self._login()
        with mock.patch.object(app_module, "engine_error", None):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("Engine not started", body)

    def test_a_server_that_never_started_names_the_missing_flag(self):
        # The state an imported application is in until the server's start runs —
        # a gunicorn line without the hooks module stays in it (ADR-0091 decision 5).
        self._login()
        with mock.patch.object(app_module, "engine_error", app_module.NOT_STARTED):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("Engine not started", body)
        self.assertIn("--config python:little_sister.gunicorn_hooks", body)

    def test_engine_error_not_on_login_page(self):
        # the login page is standalone — the reason must not leak pre-login
        with mock.patch.object(app_module, "engine_error",
                               "checks/web.yaml: secret path leaked?"):
            body = self.client.get("/login").get_data(as_text=True)
        self.assertNotIn("Engine not started", body)
        self.assertNotIn("secret path leaked", body)

    def test_engine_error_not_in_fragment(self):
        # the banner lives in the page header, not the polled grid fragment
        self._login()
        with mock.patch.object(app_module, "engine_error", "boom"):
            body = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertNotIn("Engine not started", body)

    def test_elapsed_filter(self):
        self.assertEqual(app_module._elapsed(None), "—")
        self.assertEqual(app_module._elapsed(0.412), "412 ms")
        self.assertEqual(app_module._elapsed(3.14159), "3.1 s")
        self.assertEqual(app_module._elapsed(42.7), "43 s")
        # past a minute it climbs, which is the whole reason it exists: the
        # system page used to render a two-minute run as `115 s`
        self.assertEqual(app_module._elapsed(115), "1m 55s")
        self.assertEqual(app_module._elapsed(7620), "2h 7m")
        self.assertEqual(app_module._elapsed(97200), "1d 3h")

    def _system_body(self, checks):
        """Render /system against a stub engine reporting ``checks``."""
        from little_sister.engine import EngineInfo
        info = EngineInfo(
            started_at="2026-07-20T10:00:00", uptime_seconds=5.0,
            max_workers=8, check_count=len(checks), running=0, checks=checks)
        stub = mock.Mock()
        stub.info.return_value = info
        with mock.patch.object(app_module, "engine", stub):
            return self.client.get("/system").get_data(as_text=True)

    def test_system_shows_type_and_schedule_columns(self):
        # per check: its type, and Running / Next run / Last run each as a
        # time-of-day (configured timezone) plus a muted interval
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="http", frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:40+00:00",
                      next_in_seconds=100.0,
                      last_run_at="2026-07-20T13:50:57+00:00",
                      elapsed_seconds=0.412),
            CheckInfo(path="/svc/b", type_name="ssh-script",
                      frequency_seconds=60, running=True,
                      running_since="2026-07-20T13:51:00+00:00",
                      running_seconds=3.4,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None)))
        self.assertIn("Type", body)
        self.assertIn("http", body)
        self.assertIn("ssh-script", body)          # same-root checks stay apart
        # timestamps render as time of day in the configured tz (UTC+2 in July)
        self.assertIn("15:52:40", body)            # next run, check a
        self.assertIn("· in 1m 40s", body)         # not `in 100s` — one reading
        self.assertIn("15:50:57", body)            # last run start, check a
        self.assertIn("· 412 ms", body)
        self.assertIn("15:51:00", body)            # running since, check b
        self.assertIn("· 3.4 s", body)
        self.assertIn("—", body)                   # check b has no last run yet
        self.assertNotIn(">running<", body)        # the old placeholder is gone

    def test_system_shows_a_declared_record_beside_the_one_it_measured(self):
        # ADR-0075 decision 8: an estimate nobody can compare against a
        # measurement decays invisibly, so both stand in one cell
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="github", frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0,
                      last_run_at="2026-07-20T13:50:57+00:00",
                      elapsed_seconds=0.4,
                      expected_record=1_024, record_bytes=612),))
        self.assertIn("1,024 B record", body)
        self.assertIn("(612 B seen)", body)
        self.assertNotIn("floor", body)

    def test_system_says_when_the_floor_raised_a_declared_record(self):
        # the effective size is what startup compared, and the type's own number
        # stays visible beside it, so the page neither over-claims nor hides it
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="small", frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None, expected_record=331,
                      stated_record=64),))
        self.assertIn("331 B record (floor; declares 64 B)", body)

    def test_system_measures_a_record_nobody_declared(self):
        # the measurement stands on its own: a record no type estimated is still
        # worth watching grow
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="github", frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None, record_bytes=612),))
        self.assertIn("(612 B seen)", body)
        self.assertNotIn("B record", body)

    def test_system_marks_a_seen_record_the_seam_refused_for_its_weight(self):
        # ADR-0093 decision 6: the heaviest record the run produced, refused ones
        # included — a declaration failing is what this column exists to show
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="github", frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None, expected_record=1_024,
                      record_bytes=2_811, record_refused=True),))
        self.assertIn("(2,811 B seen, refused)", body)

    def test_system_says_what_each_check_is_reached_through(self):
        # the graph on one page (backlog #38 A): *how many* checks one
        # dependency can quiet is the question to ask before declaring it, and
        # node by node it is not a question anybody asks
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="http", frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None, depends_on="/net/vpn"),
            CheckInfo(path="/net/vpn", type_name="ssh-command",
                      frequency_seconds=60,
                      running=False, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None),))
        self.assertIn('<th>Through</th>', body)
        self.assertIn('href="/status/net/vpn">/net/vpn</a>', body)

    def test_system_queued_run_is_not_running(self):
        # submitted but still waiting for a worker: no start time to show yet
        from little_sister.engine import CheckInfo
        self._login()
        body = self._system_body((
            CheckInfo(path="/svc/a", type_name="command", frequency_seconds=60,
                      running=True, running_since=None, running_seconds=None,
                      next_run_at="2026-07-20T13:52:00+00:00",
                      next_in_seconds=60.0, last_run_at=None,
                      elapsed_seconds=None),))
        self.assertIn("queued", body)

    def _a_check(self, path, type_name):
        from little_sister.engine import CheckInfo
        return CheckInfo(path=path, type_name=type_name, frequency_seconds=60,
                         running=False, running_since=None,
                         running_seconds=None,
                         next_run_at="2026-07-20T13:52:00+00:00",
                         next_in_seconds=60.0, last_run_at=None,
                         elapsed_seconds=None)

    def test_system_roster_leads_with_the_types_in_use(self):
        # the roster answers two questions and only one is urgent: *which code
        # answers for `type: http`* concerns the handful of types the config
        # names, so those come first, counted, and the rest fold away
        self._login()
        body = self._system_body((self._a_check("/svc/a", "http"),))
        self.assertIn("<code>http</code>", body)
        self.assertIn("used by 1 check</summary>", body)
        fold = body.index("unused by this configuration")
        self.assertLess(body.index("<code>http</code>"), fold)
        # …and a type nobody configured is still there, below the fold
        self.assertGreater(body.index("<code>ssh-script</code>"), fold)

    def test_system_roster_counts_the_checks_behind_a_type(self):
        # one row per type, not per check — the count is what says how much of
        # this configuration rides on that code, without repeating the module and
        # version once per check. "used by", because a bare "2 checks" under a type
        # name reads as two checks the package *brought*, which is the opposite of
        # what it counts: one type serving two configured checks is the norm.
        self._login()
        body = self._system_body((self._a_check("/svc/a", "http"),
                                  self._a_check("/svc/b", "http")))
        self.assertEqual(body.count("<code>http</code>"), 1)
        self.assertIn("used by 2 checks</summary>", body)

    def _roster_disclosure(self, body, type_name):
        """The `used by N …` disclosure on the roster row for ``type_name``, as
        (summary text, the node paths it lists, the hrefs those paths link to)."""
        row = body.split(f"<code>{type_name}</code>", 1)[1].split("</td>", 1)[0]
        if "<details" not in row:
            return None, [], []
        block = row.split("<details", 1)[1]
        summary = re.search(r"<summary[^>]*>(.*?)</summary>", block, re.S).group(1)
        listed = re.findall(r'<li><a href="([^"]+)">([^<]+)</a></li>', block)
        return summary.strip(), [text for _, text in listed], [
            href for href, _ in listed]

    def test_system_roster_count_opens_into_the_checks_that_produced_it(self):
        # the count is the right summary at a glance, but it was the one number on
        # this page the page could not substantiate: *two of what?* — and two check
        # files naming one type, rendering in two different branches of the tree,
        # is the ordinary case rather than a defect. So the number opens into the
        # node paths behind it, each a link to that node, and an operator never has
        # to read a config file to believe it.
        self._login()
        body = self._system_body((self._a_check("/quality/github", "http"),
                                  self._a_check("/stress/github", "http")))

        summary, paths, hrefs = self._roster_disclosure(body, "http")

        self.assertEqual(summary, "used by 2 checks")
        self.assertEqual(paths, ["/quality/github", "/stress/github"])
        self.assertEqual(hrefs, ["/status/quality/github",
                                 "/status/stress/github"])

    def test_system_roster_list_is_as_long_as_the_count_says(self):
        # what makes the disclosure worth anything is that it accounts for the
        # whole number: two checks sharing one host node (ADR-0015 allows it for
        # disjoint owned subtrees) are two entries, because a list deduplicated
        # into one would leave "used by 2 checks" unsubstantiated all over again
        self._login()
        body = self._system_body((self._a_check("/host/one", "http"),
                                  self._a_check("/host/one", "http"),
                                  self._a_check("/host/two", "http")))

        summary, paths, _ = self._roster_disclosure(body, "http")

        self.assertEqual(summary, "used by 3 checks")
        self.assertEqual(paths, ["/host/one", "/host/one", "/host/two"])

    def test_the_roster_keeps_a_types_metadata_beside_its_name(self):
        # The disclosure is the one thing on this page that makes a row grow,
        # and `align-middle` — right for every other table here — then centered
        # Module, Version and From against the *path list*: measured in
        # Chromium at nine open paths, the version sat 102px below the type
        # name it answers for, beside nothing.  The roster alone is top-aligned.
        # Asserted on the roster's own table so a sweep that re-centers the
        # page cannot take this one with it.
        self._login()
        body = self._system_body((self._a_check("/host/one", "http"),))
        roster = body[body.index("<h3 class=\"h6 text-muted text-uppercase\">"
                                 "Check types</h3>"):]
        table = roster[roster.index("<table"):roster.index(">", roster.index(
            "<table"))]
        self.assertIn("align-top", table)
        self.assertNotIn("align-middle", table)

    def _an_installed_type(self, module_file):
        from little_sister.checks.base import TypeOrigin
        return TypeOrigin(type_name="github", module="little_sister_github.github",
                          package="little_sister_github",
                          distribution="little-sister-github", version="0.1.0",
                          path=module_file)

    def test_system_draws_a_loaded_path_against_the_environment(self):
        # the row's diagnostic is *which root* the module came from, not the
        # absolute string — nine tenths of which is the same prefix on every row,
        # starting with somebody's home directory
        import sysconfig
        purelib = sysconfig.get_paths()["purelib"]
        absolute = str(Path(purelib) / "little_sister_github" / "github.py")
        self._login()

        with mock.patch.object(app_module, "registered_types",
                               lambda: [self._an_installed_type(absolute)]):
            body = self._system_body((self._a_check("/quality/github", "github"),))

        shown = f"{Path(purelib).name}/little_sister_github/github.py"
        self.assertIn(f">{shown}</small>", body)
        self.assertNotIn(f">{absolute}</small>", body)
        # …and the whole string is still one hover away for the reader who wants it
        self.assertIn(f'title="{absolute}"', body)

    def test_system_draws_a_checkout_against_the_project(self):
        # the case the path exists for: a source copy earlier on sys.path shadows
        # an installed distribution of the same name, and the version beside it is
        # then answering for code that is not running. Still legible as such.
        absolute = str(Path.cwd() / "my_deployment" / "checks.py")
        self._login()

        with mock.patch.object(app_module, "registered_types",
                               lambda: [self._an_installed_type(absolute)]):
            body = self._system_body((self._a_check("/quality/github", "github"),))

        self.assertIn(">./my_deployment/checks.py</small>", body)
        self.assertNotIn(f">{absolute}</small>", body)

    def test_system_roster_unused_type_offers_no_list(self):
        # a type used zero times keeps no list — there is nothing to open, and the
        # fold it sits under already says so
        self._login()
        body = self._system_body((self._a_check("/svc/a", "http"),))

        summary, paths, _ = self._roster_disclosure(body, "ssh-script")

        self.assertIsNone(summary)
        self.assertEqual(paths, [])

    def test_system_roster_is_unfolded_when_nothing_is_in_use(self):
        # no engine: nothing is known to be unused, and this is the moment the
        # roster matters most (a start refused for an unknown `type:` lands
        # here), so it is shown whole rather than hidden behind a disclosure
        self._login()
        app_module.engine = None
        body = self.client.get("/system").get_data(as_text=True)
        self.assertIn("<code>http</code>", body)
        self.assertIn("<code>ssh-script</code>", body)
        self.assertNotIn("<details", body)

    def test_type_roster_splits_on_what_the_engine_runs(self):
        from little_sister.engine import EngineInfo
        checks = (self._a_check("/svc/a", "http"),
                  self._a_check("/svc/b", "http"))
        info = EngineInfo(started_at="2026-07-20T10:00:00", uptime_seconds=5.0,
                          max_workers=8, check_count=2, running=0,
                          checks=checks)

        in_use, folded = app_module._type_roster(info)

        self.assertEqual([(r.origin.type_name, r.count) for r in in_use],
                         [("http", 2)])
        # the row carries the paths, in the engine's order — the same order the
        # check table above it prints — which is what lets the count be opened
        self.assertEqual([r.paths for r in in_use], [("/svc/a", "/svc/b")])
        self.assertNotIn("http", [r.origin.type_name for r in folded])
        self.assertIn("ssh-script", [r.origin.type_name for r in folded])
        self.assertEqual({r.paths for r in folded}, {()})
        # nothing to split against — everything folds, and the template unfolds it
        self.assertEqual(app_module._type_roster(None)[0], [])

    def test_localtime_filter_accepts_explicit_format(self):
        # the format is overridable, the timezone never is (ADR-0006)
        self.assertEqual(
            app_module._localtime("2026-06-19T10:00:00+00:00", "%H:%M:%S"),
            "12:00:00")

    def test_stamp_seeded_from_server(self):
        # the page dates its data itself — no "live" placeholder
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertRegex(
            body, r'data-rendered-at="\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"')
        self.assertRegex(
            body, r'updated \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        self.assertNotIn(">live<", body)

    def test_localtime_filter_uses_configured_tz(self):
        # default config timezone is Europe/Berlin; June is CEST (UTC+2)
        self.assertEqual(app_module._localtime("2026-06-19T10:00:00+00:00"),
                         "2026-06-19 12:00:00")
        self.assertEqual(app_module._localtime(""), "—")
        self.assertEqual(app_module._localtime("not-a-time"), "not-a-time")

    def test_format_local_uses_configured_tz_and_format(self):
        # _format_local backs both the localtime filter and the poll stamp: it
        # renders config.time_format in config.timezone (default Europe/Berlin,
        # CEST/UTC+2 in June), so the dashboard clock never falls back to the
        # browser's locale (ADR-0006).
        from datetime import datetime
        moment = datetime.fromisoformat("2026-06-19T10:00:00+00:00")
        self.assertEqual(app_module._format_local(moment), "2026-06-19 12:00:00")

    def test_status_fragment_carries_rendered_at_header(self):
        # the poll fragment hands the client a server-formatted timestamp so
        # "updated …" honors config.time_format rather than toLocaleTimeString
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        stamp = self.client.get("/status?fragment=1").headers.get("X-Rendered-At")
        self.assertIsNotNone(stamp)
        # configured format is "%Y-%m-%d %H:%M:%S": 24-hour, no AM/PM
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertNotIn("AM", stamp)
        self.assertNotIn("PM", stamp)

    def test_poller_shows_server_stamp_not_client_clock(self):
        # the shared poll displays the server header, not a local Date
        js = self.client.get("/static/js/poll.js").get_data(as_text=True)
        self.assertIn("X-Rendered-At", js)
        self.assertNotIn("toLocaleTimeString", js)
        self.assertNotIn("new Date", js)

    # ----- the brand -----

    def test_bar_reads_the_brand_sentence_instead_of_overview(self):
        # the placeholder title is gone and the bar carries the whole sentence
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("Overview", body)
        self.assertIn("little sister", body)
        self.assertIn("is watching for you", body)

    def test_brand_is_the_way_home(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('<a class="navbar-brand ls-brand" href="/">', body)

    def test_mark_carries_both_eyes_so_the_wink_has_something_to_swap(self):
        # the wink is a group swap, not an image: both states must be in the DOM
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="ls-eye-open"', body)
        self.assertIn('class="ls-eye-shut"', body)

    def test_dashboard_shows_the_mark_not_the_gaze(self):
        # motion policy: the pair (which blinks on its own) never reaches the
        # dashboard — the bar gets the single mark, which only winks on hover
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-brand__mark", body)
        self.assertNotIn("ls-gaze", body)

    def test_login_page_gets_the_full_brand_moment(self):
        body = self.client.get("/login").get_data(as_text=True)
        self.assertIn("ls-gaze", body)
        self.assertIn("little sister", body)
        self.assertIn("is watching for you", body)
        # the gaze is the pair, and both eyes blink together
        self.assertEqual(body.count('class="ls-eye-open"'), 2)
        self.assertEqual(body.count('class="ls-eye-shut"'), 2)

    def test_brand_name_is_written_in_one_place_and_overridable(self):
        # _brand.html defaults the name but reads a variable, which is the seam
        # the web-customization phase takes over
        from flask import render_template
        with app_module.app.test_request_context():
            self.assertIn("little sister", render_template("_brand.html"))
            rendered = render_template("_brand.html", brand_name="big sister")
            self.assertIn("big sister", rendered)
            self.assertNotIn("little sister", rendered)

    def test_every_page_links_the_self_inking_svg_tab_icon(self):
        self._login()
        for path in ("/status", "/login"):
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertIn(
                    '<link rel="icon" type="image/svg+xml" '
                    'href="/static/favicon.svg">', body)
                # the PNG fallbacks stay for browsers that ignore the SVG
                self.assertIn("/static/favicon-32x32.png", body)

    def test_svg_tab_icon_re_inks_itself_for_dark_tabs(self):
        svg = self.client.get("/static/favicon.svg").get_data(as_text=True)
        self.assertIn("prefers-color-scheme: dark", svg)

    def test_manifest_finally_names_the_app(self):
        # the shipped manifest had empty name/short_name placeholders
        import json
        manifest = json.loads(
            self.client.get("/static/site.webmanifest").get_data(as_text=True))
        self.assertEqual(manifest["name"], "little sister")
        self.assertEqual(manifest["short_name"], "little sister")
        self.assertEqual(manifest["theme_color"], "#f8f9fa")

    # ----- the shell: rail, bar, band -----

    def test_rail_is_the_default_layout(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-layout="rail"', body)

    def test_sections_are_written_once_and_reach_both_layouts(self):
        # one entry list, rendered into the rail and into the bar; CSS shows
        # whichever the layout asks for
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        for href in ("/events", "/maintenance", "/links", "/copy"):
            with self.subTest(href=href):
                self.assertEqual(body.count(f'href="{href}"'), 2)

    def test_admin_only_section_still_obeys_the_session_in_both_layouts(self):
        # the fixture user is an admin, so System is emitted — once per layout;
        # logged out there is no shell at all to carry it
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('href="/system"'), 2)
        self.client.get("/logout")
        login = self.client.get("/login").get_data(as_text=True)
        self.assertNotIn('href="/system"', login)
        self.assertNotIn("ls-rail", login)

    def test_rail_marks_the_section_you_are_looking_at(self):
        self._login()
        body = self.client.get("/events").get_data(as_text=True)
        self.assertIn('class="ls-rail__item is-on" href="/events"', body)
        self.assertIn('aria-current="page"', body)

    def test_a_branch_page_still_counts_as_the_status_section(self):
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        body = self.client.get("/status/svc").get_data(as_text=True)
        self.assertIn('class="ls-rail__item is-on" href="/status"', body)

    def test_every_page_that_opens_the_shell_also_closes_it(self):
        # the pages are standalone documents, so nothing closes the shell for
        # them — a page that forgets _page_end.html renders subtly broken
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        for path in ("/status", "/status/svc/web", "/events", "/maintenance",
                     "/links", "/copy", "/system"):
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertEqual(body.count('<div class="ls-shell">'), 1)
                self.assertEqual(body.count("</main>"), 1)
                # and the shell closes before the document does
                self.assertLess(body.index("</main>"), body.index("</body>"))

    def test_the_freshness_stamp_moved_into_the_band_but_not_into_the_grid(self):
        # the band gathers it; the poll still swaps only #status-grid, so the
        # stamp must stay outside that container
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="ls-band__meta"', body)
        self.assertLess(body.index('id="status-updated"'),
                        body.index('<div id="status-grid">'))

    def test_the_polled_fragment_still_carries_no_stamp(self):
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        fragment = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertNotIn("status-updated", fragment)
        self.assertNotIn("ls-band", fragment)
        self.assertIn("status-card", fragment)   # the grid itself still swaps

    def test_stamp_keeps_the_class_the_poll_swaps_for_danger(self):
        # poll.js swaps .text-muted for .text-danger and both are !important in
        # Bootstrap, so the band must not color this line itself
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="text-muted ls-band__updated" id="status-updated"',
                      body)
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        rule = css.split(".ls-band__updated {", 1)[1].split("}", 1)[0]
        self.assertNotIn("color", rule)

    def test_filters_sit_in_the_band_beside_the_stamp(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        meta = body.split('class="ls-band__meta"', 1)[1].split("</div>", 1)[0]
        self.assertIn("status-updated", meta)
        band = body.split('<div class="ls-band">', 1)[1]
        self.assertIn('class="status-filters', band.split("</div>\n</div>")[0])

    def test_detail_page_gets_the_band_without_stamp_or_filters(self):
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        body = self.client.get("/status/svc/web").get_data(as_text=True)
        self.assertIn('<div class="ls-band">', body)
        self.assertIn("crumb", body)              # the deep breadcrumb stays
        self.assertNotIn("status-updated", body)  # nothing polls this page
        self.assertNotIn("status-filters", body)

    def test_both_layouts_are_styled_so_choosing_one_is_all_it_takes(self):
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        self.assertIn('body[data-ls-layout="rail"] .ls-rail', css.replace(
            'body[data-ls-layout="rail"] .ls-bar__nav',
            'body[data-ls-layout="rail"] .ls-rail'))
        self.assertIn('body[data-ls-layout="topbar"] .ls-rail', css)

    def test_burger_state_is_not_persisted_anywhere(self):
        js = self.client.get("/static/js/rail.js").get_data(as_text=True)
        self.assertIn("is-expanded", js)
        self.assertIn("aria-expanded", js)
        for store in ("localStorage", "sessionStorage", "document.cookie"):
            with self.subTest(store=store):
                self.assertNotIn(store, js)

    # ----- themes & the settings menu (ADR-0028/0029) -----

    def _prefs(self, value):
        self.client.set_cookie("ls_prefs", value)

    def test_no_cookie_means_the_defaults(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-theme="default"', body)
        self.assertIn('data-ls-layout="rail"', body)

    def test_a_saved_preference_is_rendered_by_the_server(self):
        # server-side, so the page never flashes the wrong scheme
        self._login()
        self._prefs("theme=dark&layout=topbar")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-theme="dark"', body)
        self.assertIn('data-ls-layout="topbar"', body)

    def test_junk_in_the_cookie_falls_back_per_key(self):
        # a preference is a look: a bad one may never break a page, and one bad
        # key may not take the other down with it
        self._login()
        for cookie, theme, layout in [
                ("", "default", "rail"),
                ("nonsense", "default", "rail"),
                ("theme=&layout=", "default", "rail"),
                ("theme=chartreuse&layout=topbar", "default", "topbar"),
                ("theme=dark&layout=hovercraft", "dark", "rail"),
                ("theme=dark&theme=vivid", "dark", "rail"),
                ("%%%=&&&", "default", "rail")]:
            with self.subTest(cookie=cookie):
                self._prefs(cookie)
                body = self.client.get("/status").get_data(as_text=True)
                self.assertIn(f'data-ls-theme="{theme}"', body)
                self.assertIn(f'data-ls-layout="{layout}"', body)

    def test_choosing_a_theme_writes_the_cookie_and_comes_back(self):
        self._login()
        response = self.client.post("/preferences",
                                    data={"theme": "vivid", "next": "/events"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/events"))
        cookie = response.headers["Set-Cookie"]
        self.assertIn("ls_prefs=theme=vivid", cookie)
        self.assertIn("layout=rail", cookie)      # the untouched key rides along
        self.assertIn("Max-Age=31536000", cookie)   # a year, like the view cookies
        self.assertIn("SameSite=Lax", cookie)
        # and the choice is what the next page renders
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-theme="vivid"', body)

    def test_a_choice_keeps_the_other_preference(self):
        self._login()
        self.client.post("/preferences", data={"theme": "dark", "next": "/status"})
        self.client.post("/preferences", data={"layout": "topbar", "next": "/status"})
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-theme="dark"', body)
        self.assertIn('data-ls-layout="topbar"', body)

    def test_a_hand_edited_form_cannot_write_junk(self):
        self._login()
        self.client.post("/preferences", data={"theme": "dark", "next": "/status"})
        self.client.post("/preferences",
                         data={"theme": "../../etc/passwd", "next": "/status"})
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-theme="dark"', body)      # the last good value

    def test_the_return_field_cannot_become_an_open_redirect(self):
        self._login()
        for target in ("https://evil.example/steal", "//evil.example/steal",
                       # a browser normalizes `\` to `/` and strips tabs, so
                       # both of these *arrive* as the scheme-relative form
                       "/\\evil.example/steal", "/\t/evil.example/steal",
                       "javascript:alert(1)", ""):
            with self.subTest(target=target):
                response = self.client.post(
                    "/preferences", data={"theme": "dark", "next": target})
                self.assertTrue(
                    response.headers["Location"].endswith("/status"),
                    response.headers["Location"])

    def test_preferences_needs_a_login(self):
        response = self.client.post("/preferences", data={"theme": "dark"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_dark_themes_carry_bootstrap_along(self):
        # Bootstrap's own chrome only follows where data-bs-theme reaches
        self._login()
        for theme, expected in [("dark", True), ("cyberpunk", True),
                                ("default", False), ("vivid", False),
                                ("pastel", False), ("auto", False)]:
            with self.subTest(theme=theme):
                self._prefs(f"theme={theme}")
                body = self.client.get("/status").get_data(as_text=True)
                self.assertEqual('data-bs-theme="dark"' in body, expected)

    def test_auto_is_resolved_in_the_browser_because_the_server_cannot(self):
        self._login()
        self._prefs("theme=auto")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("prefers-color-scheme: dark", body)
        self.assertIn("data-bs-theme", body)             # ...set by the script
        self.assertNotIn('data-bs-theme="dark"', body)    # ...not by the server

    def test_the_menu_offers_the_whole_roster(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        for theme in ("auto", "default", "vivid", "pastel", "dark", "cyberpunk"):
            with self.subTest(theme=theme):
                self.assertIn(f'name="theme" value="{theme}"', body)
        for layout in ("rail", "topbar", "kiosk"):
            with self.subTest(layout=layout):
                self.assertIn(f'name="layout" value="{layout}"', body)

    def test_the_menu_trigger_shows_the_configured_avatar_beside_the_user(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="ls-menu__avatar"', body)
        self.assertIn('src="/user/avatar"', body)
        self.assertIn('alt=""', body)

        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        self.assertIn(".ls-menu__avatar", css)
        self.assertIn("object-fit: cover", css)
        self.assertIn("border-radius: 50%", css)

    def test_the_menu_trigger_uses_the_default_when_no_avatar_resolved(self):
        self._login()
        with mock.patch.dict(local_login.registered_avatars(), {}, clear=True):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('src="/static/default-avatar.svg"', body)

    def test_every_layout_is_choosable(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        for layout in ("rail", "topbar", "kiosk"):
            with self.subTest(layout=layout):
                markup = body.split(f'value="{layout}"', 1)[1].split(">", 1)[0]
                self.assertNotIn("disabled", markup)

    # ----- the kiosk -----

    def _kiosk(self):
        self._login()
        self.client.set_cookie("ls_prefs", "layout=kiosk")

    def test_kiosk_is_one_line_and_nothing_else(self):
        self._kiosk()
        self.tree.upsert("/svc/web", StatusCode.OK)
        self.tree.upsert(HEARTBEAT_PATH, StatusCode.OK)   # so the strip renders
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-kiosk", body)          # the slim line
        self.assertIn("ls-strip", body)          # strip and grid stay
        self.assertIn("status-grid", body)
        for gone in ("ls-bar", "ls-rail", "ls-menu", "status-filters", "ls-band"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)

    def test_the_kiosk_line_carries_the_brand_sentence(self):
        self._kiosk()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("little sister", body)
        self.assertIn("is watching for you", body)
        # round 5 drew brand, stamp and exit — no breadcrumb at any depth
        self.assertNotIn("crumb", body)

    def test_the_kiosk_keeps_exactly_one_freshness_stamp(self):
        # the poller finds it by id, so a second one would be a real defect
        self._kiosk()
        for path in ("/status", "/system"):
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertEqual(body.count('id="status-updated"'), 1)
                self.assertIn("data-rendered-at=", body)

    def test_a_stale_kiosk_can_still_say_so(self):
        # escalation (ADR-0005) needs the stamp outside the polled container and
        # the poll wired to the same target as the dashboard — an unattended
        # screen is exactly where a frozen grid must announce itself
        self._kiosk()
        self.tree.upsert("/svc/web", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertLess(body.index('id="status-updated"'),
                        body.index('<div id="status-grid">'))
        self.assertIn('data-target="status-grid"', body)
        self.assertIn("js/poll.js", body)
        fragment = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertNotIn("status-updated", fragment)

    def test_exit_writes_the_default_layout_back_and_goes_home(self):
        self._kiosk()
        body = self.client.get("/events").get_data(as_text=True)
        self.assertIn("ls-kiosk__exit", body)
        # the exit posts the default layout to the same route the menu uses
        form = body.split('class="ls-kiosk__form"', 1)[1].split("</form>", 1)[0]
        self.assertIn('action="/preferences"', form)
        self.assertIn('name="layout" value="rail"', form)
        self.assertIn('name="next" value="/status"', form)
        response = self.client.post("/preferences",
                                    data={"layout": "rail", "next": "/status"})
        self.assertTrue(response.headers["Location"].endswith("/status"))
        after = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-layout="rail"', after)
        self.assertNotIn("ls-kiosk", after)
        self.assertIn("ls-rail", after)

    def test_the_kiosk_reaches_every_page_so_exit_is_never_out_of_reach(self):
        self._kiosk()
        for path in ("/status", "/events", "/maintenance", "/links", "/system"):
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertIn("ls-kiosk__exit", body)
                self.assertNotIn("ls-rail", body)
                # and the shell still closes exactly once
                self.assertEqual(body.count("</main>"), 1)

    def test_an_engine_failure_still_shouts_on_a_kiosk(self):
        self._kiosk()
        with mock.patch.object(app_module, "engine_error", "boom"):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("Engine not started", body)

    def test_a_kiosk_cookie_is_still_honoured_even_though_unoffered(self):
        self._login()
        self._prefs("layout=kiosk")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-layout="kiosk"', body)

    def test_logout_moved_into_the_menu_and_out_of_the_bar(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("ls-menu__logout", body)
        self.assertNotIn("btn-outline-danger", body)
        self.assertEqual(body.count('href="/logout"'), 1)

    def test_menu_reserves_the_later_per_user_settings(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("settings", body)
        self.assertIn("is-disabled", body)

    def test_every_theme_has_a_block_in_the_stylesheet(self):
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        for theme in ("vivid", "pastel", "dark", "cyberpunk"):
            with self.subTest(theme=theme):
                self.assertIn(f'body[data-ls-theme="{theme}"]', css)
        # default needs no block: it *is* the :root set the others override
        self.assertIn('body[data-ls-theme="auto"]', css)

    def test_auto_dark_and_dark_stay_the_same_palette(self):
        # auto's dark half is a second copy of the dark block (a media query
        # cannot share a selector with one outside it) — so guard the drift
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)

        def tokens(selector):
            block = css.split(selector, 1)[1].split("{", 1)[1].split("}", 1)[0]
            return sorted(line.strip() for line in block.splitlines()
                          if line.strip().startswith("--ls-"))

        self.assertEqual(tokens('body[data-ls-theme="dark"]'),
                         tokens('body[data-ls-theme="auto"]'))
        self.assertGreater(len(tokens('body[data-ls-theme="dark"]')), 15)

    def test_the_login_page_wears_the_theme_but_has_no_layout(self):
        self._prefs("theme=dark&layout=topbar")
        body = self.client.get("/login").get_data(as_text=True)
        self.assertIn('data-ls-theme="dark"', body)
        self.assertNotIn("data-ls-layout", body)
        self.assertNotIn("ls-menu", body)

    # ----- /about -----

    def test_about_requires_a_login_like_everything_else(self):
        response = self.client.get("/about")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_about_introduces_the_thing_that_is_watching(self):
        self._login()
        body = self.client.get("/about").get_data(as_text=True)
        self.assertIn("ls-gaze", body)                 # the pair, at full size
        self.assertIn("little sister", body)
        self.assertIn("is watching for you", body)
        self.assertIn("Big Brother", body)             # the naming rationale
        # The name wears the brand accent wherever it is said. Counted **in the
        # story**, because the hero's lines are a draw and several of them say
        # her name too — a fixed total here fails on the days it is drawn.
        story = body.split("ls-about__story", 1)[1].split("ls-about__repo", 1)[0]
        self.assertEqual(story.count('<span class="ls-accent">little sister</span>'), 2)
        self.assertIn("ls-about__coda", body)
        self.assertIn(__version__, body)
        self.assertIn("github.com/m-31/little-sister", body)

    def test_about_is_reachable_from_both_layouts(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        # once at the rail's foot, once as the bar's trailing entry
        self.assertEqual(body.count('href="/about"'), 2)
        # ...and the rail's copy comes after the spacer that pushes it down
        self.assertLess(body.index('class="ls-rail__spacer"'),
                        body.index('class="ls-rail__item" href="/about"'))

    def test_about_marks_itself_as_the_current_section(self):
        self._login()
        body = self.client.get("/about").get_data(as_text=True)
        self.assertIn('class="ls-rail__item is-on" href="/about"', body)

    def test_the_hero_watches_only_on_about_and_only_if_motion_is_welcome(self):
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        self.assertIn('class="ls-hero" id="ls-hero"', about)
        # the field is decoration; the prose says the same thing better
        self.assertIn('class="ls-hero__field" aria-hidden="true"', about)
        # the dashboard stays still
        self.assertNotIn("ls-hero",
                         self.client.get("/status").get_data(as_text=True))
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        # the sheet gates motion in several places; read the hero's own section
        hero = css.split("/* ----- /about: the hero -----", 1)[1]
        still, motion = hero.split(
            "@media (prefers-reduced-motion: no-preference)", 1)
        # every one of the hero's animations is declared inside the query, so a
        # rule that forgets an override cannot leak past it
        for name in ("ls-hero-orbit", "ls-hero-say", "ls-hero-stay",
                     "ls-hero-settle"):
            with self.subTest(animation=name):
                self.assertIn(name, motion)
                self.assertNotIn(name, still)

    def test_the_identity_is_told_once(self):
        # It used to be three claims on one attention: the bar, a block of its
        # own, and an animation with a second eye inside it.
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        self.assertEqual(about.count('class="ls-gaze"'), 1)
        self.assertEqual(about.count("ls-brand__wordmark"), 2)   # bar + hero
        self.assertIn("ls-hero__version", about)
        self.assertNotIn("ls-about__brand", about)

    def test_the_orbit_carries_the_terms_the_story_names(self):
        # The paragraph is the legend for the field: every topic in the prose is
        # a term in orbit, or the glow would point at nothing.
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        for signal in watch_lines.TOPICS:
            with self.subTest(topic=signal.topic):
                self.assertIn(f'data-topic="{signal.topic}"><b>{signal.name}</b>',
                              about.replace("\n", "").replace("  ", ""))
                self.assertIn(f'class="ls-topic" data-topic="{signal.topic}"', about)

    def test_every_line_the_hero_says_comes_from_the_pools(self):
        # The draw is the point of the pools, so what a render may show is
        # everything in them — checked over enough renders to see several draws.
        self._login()
        allowed = set(watch_lines.TICKER) | set(watch_lines.CLOSING)
        for lines in watch_lines.OBSERVATIONS:
            allowed |= set(lines)
        for _ in range(12):
            for line in watch_lines.says():
                with self.subTest(line=line):
                    self.assertIn(line, allowed)

    def test_the_hero_says_its_lines_from_the_pools(self):
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        self.assertEqual(about.count("ls-hero__line"), len(watch_lines.says()))
        # the ending is fixed, and it is the last thing said
        self.assertLess(about.index("Systems change."),
                        about.index("little sister</span> is watching for you."))

    def test_her_name_wears_the_house_colour_wherever_it_is_said(self):
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        said = '<span class="ls-accent">little sister</span> is watching for you.'
        self.assertIn(said, about)
        self.assertNotIn(">little sister is watching for you.<", about)

    def test_the_seen_pairing_is_a_file_not_an_inline_script(self):
        # An inline script is the one thing that would stop a
        # Content-Security-Policy later, which this codebase avoids everywhere.
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        self.assertIn("js/watch.js", about)
        self.assertNotIn("setTimeout", about)
        script = self.client.get(
            "/static/js/watch.js").get_data(as_text=True)
        self.assertIn("prefers-reduced-motion: reduce", script)
        self.assertIn("data-topic", script)

    def test_asking_for_stillness_leaves_the_last_line_standing(self):
        # Rings that turn and a term lighting up on its own are both motion,
        # whatever they are worth.
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        hero = css.split("/* ----- /about: the hero -----", 1)[1]
        still = hero.split("@media (prefers-reduced-motion: no-preference)", 1)[0]
        # standing still, the ending *is* its last line — and it is the one that
        # says what the page is for
        self.assertIn(".ls-hero__line:last-child { opacity: 1; }", still)
        line_rule = still.split(".ls-hero__line {", 1)[1].split("}", 1)[0]
        self.assertIn("opacity: 0", line_rule)

    def test_the_repository_link_is_a_footnote_not_a_chapter_break(self):
        self._login()
        about = self.client.get("/about").get_data(as_text=True)
        self.assertLess(about.index("ls-about__coda"), about.index("ls-about__repo"))

    # ----- the tab: title and icons -----

    def test_every_tab_says_which_page_and_whose_it_is(self):
        # the page first, so a narrow tab still identifies itself — and because
        # poll.js prefixes "(stale) " to whatever this says
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        for path, page in [("/status", "Status"), ("/events", "Events"),
                           ("/maintenance", "Maintenance"), ("/links", "Links"),
                           ("/system", "System"), ("/about", "About"),
                           # the detail page names the node, not the section
                           ("/copy", "Copy"), ("/status/svc/web", "web")]:
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertIn(f"<title>{page} · little sister</title>", body)

    def test_the_login_tab_is_branded_too(self):
        body = self.client.get("/login").get_data(as_text=True)
        self.assertIn("<title>Login · little sister</title>", body)

    def test_the_tab_takes_its_name_from_the_one_place_it_is_written(self):
        from flask import render_template
        with app_module.app.test_request_context("/status"):
            rendered = render_template("_header.html", firstname="Peter",
                                       page_title="Status",
                                       brand_name="big sister")
            self.assertIn("<title>Status · big sister</title>", rendered)

    def test_the_shipped_icon_set_is_all_actually_referenced(self):
        # the .ico used to be shipped and linked by nothing at all
        self._login()
        for path in ("/status", "/login"):
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                for asset in ("favicon.ico", "favicon.svg", "favicon-32x32.png",
                              "favicon-16x16.png", "apple-touch-icon.png",
                              "site.webmanifest"):
                    self.assertIn(f"/static/{asset}", body, asset)
        # the android icons are the manifest's business
        manifest = self.client.get(
            "/static/site.webmanifest").get_data(as_text=True)
        self.assertIn("android-chrome-192x192.png", manifest)
        self.assertIn("android-chrome-512x512.png", manifest)

    def test_the_vivid_edge_follows_its_surfaces_own_ink(self):
        # the edge is the only separator when a culprit sits inside a parent of
        # its own status, and a literal white one vanished on the warn yellow —
        # and would now do the same on the error red, whose ink also went dark
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        self.assertIn("--ls-vivid-edge: color-mix(in srgb, currentColor 45%,"
                      " transparent);", css)
        self.assertNotIn("rgba(255, 255, 255, 0.45)", css)

    def test_the_history_button_belongs_to_the_palette(self):
        # btn-info was the one color on the detail page that followed no theme
        self._login()
        self.tree.upsert("/svc/web", StatusCode.OK)
        body = self.client.get("/status/svc/web").get_data(as_text=True)
        self.assertNotIn("btn-info", body)
        self.assertIn("btn-outline-secondary", body)
        self.assertIn("History", body)

    def test_brand_motion_is_gated_on_reduced_motion(self):
        # the wink and the blink both live inside the no-preference query, so a
        # visitor who asked for stillness gets a brand that never moves
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        gate = "@media (prefers-reduced-motion: no-preference)"
        self.assertIn(gate, css)
        motion = css.split(gate, 1)[1]
        for rule in (".ls-brand:hover .ls-eye-shut", ".ls-gaze .ls-eye-open"):
            self.assertIn(rule, motion)


class LinksPageTests(TestCase):
    """`/links` — the shared toolbox (ADR-0030)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def page(self, config, view=None):
        """Render `/links` for one configuration, with the network held out.

        Opening the page is also what **triggers** a probe pass (ADR-0030 §9), and
        one of the fixtures below names a remote icon — so the trigger is stubbed
        here and exercised in `test_link_probe.py`, where the request layer is
        patched. `view` is what the render is handed; the default is the state
        before anything has been asked.
        """
        with (mock.patch.object(app_module, "current_links", return_value=config),
              mock.patch.object(app_module.link_probe, "refresh_if_due"),
              mock.patch.object(app_module.link_probe, "page_view",
                                return_value=view or link_probe.ProbeView())):
            return self.client.get("/links").get_data(as_text=True)

    def test_requires_login(self):
        response = app_module.app.test_client().get("/links")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_renders_groups_and_entries_in_the_written_order(self):
        config = links.LinksConfig(groups=(
            links.Group(title="Loadtest Live", links=(
                links.Link(title="EMERGENCY STOP", url="https://stop.example.org/"),
                links.Link(title="Console", url="https://console.example.org/"))),
            links.Group(title="Toolbox", links=(
                links.Link(title="Cyber Chef", url="https://chef.example.org/",
                           note="offline-capable"),)),
        ))
        body = self.page(config)
        self.assertLess(body.index("EMERGENCY STOP"), body.index("Console"))
        self.assertLess(body.index("Loadtest Live"), body.index("Toolbox"))
        self.assertIn("offline-capable", body)
        self.assertIn('href="https://stop.example.org/"', body)

    def test_a_link_leaves_in_a_new_tab(self):
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/"),)),))
        body = self.page(config)
        self.assertIn('target="_blank"', body)
        self.assertIn('rel="noopener noreferrer"', body)

    def test_a_group_with_no_entries_is_not_drawn(self):
        config = links.LinksConfig(groups=(
            links.Group(title="Empty"),
            links.Group(title="Full", links=(
                links.Link(title="A", url="https://a.example.org/"),)),
        ))
        body = self.page(config)
        self.assertNotIn("Empty", body)
        self.assertIn("Full", body)

    def test_a_pair_emits_both_files_and_renders_bare(self):
        # Chosen in CSS, not here: under `auto` the server cannot know what the OS
        # resolves to, so both are emitted and one is hidden (ADR-0030 §4).
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="Grafana", icon="grafana",
                                         url="https://g.example.org/"),)),))
        body = self.page(config)
        self.assertIn("/links/icon/on-light/grafana", body)
        self.assertIn("/links/icon/on-dark/grafana", body)
        self.assertIn("ls-links__icon--light", body)
        self.assertIn("ls-links__icon--dark", body)
        self.assertNotIn("ls-links__mark--chip", body)

    def test_one_file_serves_both_backgrounds_from_one_image_on_the_chip(self):
        icon = links.Icon(name="phoenix",
                          on_light=links.IconFile(url="https://x.example.org/i.svg"),
                          on_dark=links.IconFile(url="https://x.example.org/i.svg"))
        config = links.LinksConfig(
            icons={"phoenix": icon},
            groups=(links.Group(title="T", links=(
                links.Link(title="Phoenix", icon="phoenix",
                           url="https://p.example.org/"),)),))
        body = self.page(config)
        self.assertIn("ls-links__mark--chip", body)
        self.assertEqual(body.count("https://x.example.org/i.svg"), 1)
        self.assertNotIn("ls-links__icon--dark", body)

    def test_an_undefined_name_falls_through_to_the_site_favicon(self):
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="Chef", icon="cyberchef",
                                         url="https://chef.example.org/tool"),)),))
        body = self.page(config)
        self.assertIn("https://chef.example.org/favicon.ico", body)
        self.assertIn("ls-links__mark--chip", body)

    def test_a_suppressed_icon_falls_through_too(self):
        config = links.LinksConfig(
            icons={"aws": links.Icon(name="aws", suppressed=True)},
            groups=(links.Group(title="T", links=(
                links.Link(title="AWS", icon="aws",
                           url="https://aws.example.org/"),)),))
        body = self.page(config)
        self.assertIn("https://aws.example.org/favicon.ico", body)

    def test_the_neutral_glyph_is_wired_without_an_inline_handler(self):
        # The last step of the search path, and it must not become the reason a
        # Content-Security-Policy cannot be turned on later (ADR-0030).
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/"),)),))
        body = self.page(config)
        self.assertIn('id="ls-links-glyph"', body)
        self.assertIn("js/links.js", body)
        self.assertNotIn("onerror", body)

    def test_problems_are_shown_to_whoever_maintains_the_file(self):
        config = links.LinksConfig(
            problems=("config/links.yaml: unknown key(s) grups",),
            groups=(links.Group(title="T", links=(
                links.Link(title="A", url="https://a.example.org/"),)),))
        body = self.page(config)
        self.assertIn("unknown key(s) grups", body)
        self.assertIn("alert-warning", body)

    def test_the_filter_box_is_pinned_above_the_columns_and_focused(self):
        # Past a few dozen entries this is how the page is navigated, not a
        # nicety (ADR-0030), so it arrives focused and costs no round trip.
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/"),)),))
        body = self.page(config)
        self.assertIn('id="ls-links-filter"', body)
        self.assertIn("autofocus", body)
        self.assertIn('id="ls-links-count"', body)
        self.assertIn('id="ls-links-none"', body)
        self.assertLess(body.index('id="ls-links-filter"'),
                        body.index('class="ls-links"'))

    def test_the_filter_searches_the_entry_title_and_its_group(self):
        # Lower-cased server-side, so the client compares strings and nothing
        # else; the group rides along so typing a category means the category.
        config = links.LinksConfig(groups=(links.Group(
            title="Loadtest Live", links=(
                links.Link(title="EMERGENCY STOP",
                           url="https://stop.example.org/"),)),))
        body = self.page(config)
        self.assertIn('data-ls-match="emergency stop loadtest live"', body)

    def test_a_note_is_not_searchable(self):
        # A note is prose, and a match the reader cannot see in the title it
        # landed on is what records were chosen to avoid.
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/",
                                         note="offline-capable"),)),))
        body = self.page(config)
        self.assertIn("offline-capable", body)
        self.assertNotIn('data-ls-match="a t offline-capable"', body)

    def test_the_empty_state_has_no_filter_to_offer(self):
        body = self.page(links.LinksConfig())
        self.assertNotIn('id="ls-links-filter"', body)

    def test_the_empty_state_says_where_the_file_goes(self):
        body = self.page(links.LinksConfig())
        self.assertIn("No links yet", body)
        self.assertIn("links.yaml", body)
        self.assertNotIn("ls-links__group", body)

    def test_the_empty_state_names_the_first_configuration_root(self):
        self.assertTrue(app_module._links_file_hint().endswith("links.yaml"))

    def test_the_empty_state_shows_every_installed_mark(self):
        # The reader is choosing an `icon:` name, so the page shows the whole
        # roster rather than one example: a name they cannot see is one they
        # will write wrong, and the full list otherwise only reaches the log.
        body = self.page(links.LinksConfig())
        for name in icons.known_names():
            with self.subTest(name=name):
                self.assertIn(f">{name}</code>", body)
                self.assertIn(f'src="/links/icon/on-light/{name}"', body)
                self.assertIn(f'src="/links/icon/on-dark/{name}"', body)

    def test_the_roster_is_the_registry_not_the_built_in_pack(self):
        # A deployment that installed a house pack can use its names, so it must
        # be able to read them here too (resolution is per name, ADR-0030).
        icons.register_pack("little_sister.icon_pack",
                            {"firewall": "aws-on-light.svg"})
        body = self.page(links.LinksConfig())
        self.assertIn(">firewall</code>", body)

    def test_every_mark_in_the_roster_is_served_by_the_icon_route(self):
        # The list comes from the registry rather than from `LinksConfig.icons`
        # precisely so this holds: a remote URL or a suppressed name has no bytes
        # at this route, and a row of broken images is worse than no table.
        body = self.page(links.LinksConfig())
        for name in icons.known_names():
            for variant in ("on-light", "on-dark"):
                url = f"/links/icon/{variant}/{name}"
                with self.subTest(url=url):
                    self.assertIn(f'src="{url}"', body)
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_each_variant_sits_on_the_background_it_was_drawn_for(self):
        # An on-dark mark is inked #e9edf1; on the light canvas it is invisible.
        # The two swatches are theme-invariant, so neither column can go blank.
        body = self.page(links.LinksConfig())
        self.assertLess(body.index("ls-links__swatch--light"),
                        body.index("ls-links__swatch--dark"))
        self.assertEqual(body.count("ls-links__swatch--light"),
                         len(icons.known_names()))
        self.assertEqual(body.count("ls-links__swatch--dark"),
                         len(icons.known_names()))

    def test_a_failed_mark_in_the_roster_still_reaches_the_neutral_glyph(self):
        # links.js delegates the fallback on `.ls-links__mark`, so a table image
        # only gets it by keeping that wrapper — a house pack may register half a
        # pair, and the other background 404s.
        body = self.page(links.LinksConfig())
        self.assertIn('id="ls-links-glyph"', body)
        self.assertEqual(body.count("ls-links__mark"),
                         2 * len(icons.known_names()))

    def test_a_configured_page_does_not_repeat_the_roster(self):
        # The help is the empty state: whoever has written the file is looking
        # for a link, not for a name.
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/"),)),))
        body = self.page(config)
        self.assertNotIn("ls-links__pack", body)

    def probed(self, url, alive, detail="HTTP 404", age=timedelta(hours=3)):
        """One entry that opted in, and the answer the page holds for it."""
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url=url, check=True),)),))
        verdict = link_probe.Verdict(url=url, alive=alive, detail=detail,
                                     checked_at=datetime.now() - age)
        view = link_probe.ProbeView(active=True, checked_at=verdict.checked_at,
                                    verdicts={url: verdict})
        return config, view

    def test_a_page_that_probes_nothing_has_no_freshness_line(self):
        # A `check:` block that switches everything off must not leave a permanent
        # "nothing checked yet" for a question nobody asked.
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/"),)),))
        self.assertNotIn("ls-links__probe", self.page(config))

    def test_nothing_checked_yet_is_its_own_state(self):
        config, _ = self.probed("https://a.example.org/", None)
        body = self.page(config, link_probe.ProbeView(active=True))
        self.assertIn("Nothing checked yet", body)

    def test_a_clean_page_still_says_when_it_was_checked(self):
        # Only failures are drawn beside their entries, so without this line a
        # reader cannot tell a clean page from an unprobed one.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        body = self.page(config, view)
        self.assertIn("Checked &gt; 3h ago", body)
        self.assertNotIn("ls-links__verdict", body)

    def test_an_age_is_a_floor_because_the_page_does_not_poll(self):
        # A rendered age is true for an instant; a tab left open all afternoon
        # would go on claiming "3h ago". `>` starts true and stays true.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200",
                                   age=timedelta(hours=3, minutes=20))
        self.assertIn("Checked &gt; 3h 20m ago", self.page(config, view))

    def test_a_fresh_answer_names_the_clock_instead(self):
        # Under a minute there is no floor worth stating — and "less than a
        # minute ago" is exactly the reading that rots on an open tab.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200",
                                   age=timedelta(seconds=5))
        body = self.page(config, view)
        self.assertRegex(body, r"Checked at \d\d:\d\d")
        self.assertNotIn("&lt; 1m", body)

    def test_everything_alive_is_marked_green(self):
        # A reader mid-incident reads a color before a sentence, and this is the
        # one state the page can report as good.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        body = self.page(config, view)
        self.assertIn("ls-links__probe--ok", body)
        self.assertIn("ls-links__tick", body)

    def test_one_failure_takes_the_green_away(self):
        config, view = self.probed("https://a.example.org/", False)
        body = self.page(config, view)
        self.assertNotIn("ls-links__probe--ok", body)
        self.assertNotIn("ls-links__tick", body)

    def test_an_unanswered_page_is_not_green_either(self):
        # "Nothing checked yet" is not an all-clear.
        config, _ = self.probed("https://a.example.org/", None)
        body = self.page(config, link_probe.ProbeView(active=True))
        self.assertNotIn("ls-links__probe--ok", body)

    def test_the_freshness_line_sits_in_the_filter_row(self):
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        body = self.page(config, view)
        self.assertLess(body.index('id="ls-links-filter"'),
                        body.index("ls-links__probe"))
        self.assertLess(body.index("ls-links__probe"), body.index('class="ls-links"'))

    def test_a_dead_entry_is_marked_beside_itself(self):
        # Beside the entry that failed, never on the status tree: a moved wiki page
        # must not turn the dashboard amber for everyone (ADR-0030 §9).
        config, view = self.probed("https://a.example.org/", False)
        body = self.page(config, view)
        self.assertIn("ls-links__verdict--dead", body)
        self.assertIn("HTTP 404", body)
        self.assertIn("checked &gt; 3h ago", body)

    def test_no_answer_is_not_drawn_as_a_death(self):
        # A timeout or a 500 is this instance failing to find out, not a fact about
        # the entry — so it gets the muted wording, not the danger ink.
        config, view = self.probed("https://a.example.org/", None,
                                   detail="no answer in time")
        body = self.page(config, view)
        self.assertIn("ls-links__verdict", body)
        self.assertNotIn("ls-links__verdict--dead", body)
        self.assertIn("no answer in time", body)

    def test_a_live_entry_carries_no_marker(self):
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        self.assertNotIn("HTTP 200", self.page(config, view))

    def test_an_entry_that_did_not_opt_in_shows_nothing(self):
        # The same URL may be probed because another entry asked; this one did not,
        # and a launcher must not grow a status light nobody asked for.
        url = "https://a.example.org/"
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url=url),)),))
        verdict = link_probe.Verdict(url=url, alive=False, detail="HTTP 404",
                                     checked_at=datetime.now())
        view = link_probe.ProbeView(active=True, checked_at=verdict.checked_at,
                                    verdicts={url: verdict})
        self.assertNotIn("ls-links__verdict", self.page(config, view))

    def test_a_dead_icon_joins_the_configuration_problems(self):
        # An icon is not a row on this page, so its verdict has nowhere to sit
        # beside — and the audience for both is whoever maintains the file.
        url = "https://i.example.org/m.svg"
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/",
                                         icon="far"),)),))
        failure = link_probe.IconFailure(
            name="far",
            verdict=link_probe.Verdict(url=url, alive=False, detail="HTTP 404",
                                       checked_at=datetime.now()))
        view = link_probe.ProbeView(active=True, icon_failures=(failure,))
        body = self.page(config, view)
        self.assertIn("alert-warning", body)
        self.assertIn(">far</code>", body)
        self.assertIn(url, body)

    # ----- check now -----

    def test_the_control_is_offered_where_there_is_something_to_check(self):
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        body = self.page(config, view)
        self.assertIn('action="/links/check"', body)
        self.assertIn("Check now", body)
        self.assertIn('method="post"', body)
        # `btn btn-sm` for the shape, our own ink for the color: Bootstrap's
        # outline secondary is one gray on every canvas, 3.76:1 on the dark one
        self.assertNotIn("btn-outline", body)
        # in the filter row, at the far end from the box it must not be hit from
        self.assertLess(body.index('id="ls-links-filter"'),
                        body.index("ls-links__recheck"))
        self.assertLess(body.index("ls-links__recheck"),
                        body.index('class="ls-links"'))

    def test_a_page_that_probes_nothing_offers_no_control(self):
        config = links.LinksConfig(groups=(links.Group(
            title="T", links=(links.Link(title="A", url="https://a.example.org/"),)),))
        self.assertNotIn("/links/check", self.page(config))

    def test_the_control_returns_the_viewer_to_the_page_they_pressed_on(self):
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        self.assertIn('name="next" value="/links"', self.page(config, view))

    def test_a_pass_still_running_says_so(self):
        # The page does not poll, so a press that hit its deadline would otherwise
        # look like a button that did nothing.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        self.assertIn("still checking", self.page(config, replace(view, running=True)))
        self.assertNotIn("still checking", self.page(config, view))

    def test_a_pass_that_gave_up_on_a_host_says_so(self):
        # The one condition under which the age beside it stops meaning what it
        # says (ADR-0030): without this, somebody pressing *check now* and
        # watching nothing move would conclude the button is broken rather than
        # that a target is refusing to answer.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        self.assertNotIn("ls-links__stalled", self.page(config, view))
        one = self.page(config, replace(view, stuck=1))
        self.assertIn("1 earlier pass is still waiting", one)
        self.assertNotIn("paused", one)

    def test_the_page_admits_it_when_probing_has_paused(self):
        # A different sentence, and the only one that is really an apology: at the
        # cap nothing is being probed at all until a leftover lets go.
        config, view = self.probed("https://a.example.org/", True, detail="HTTP 200")
        body = self.page(config, replace(view,
                                         stuck=link_probe.MAX_STUCK_PASSES))
        self.assertIn("paused", body)
        self.assertIn("still waiting on a host that has not answered", body)
        # Not red: a failure is drawn on the row it belongs to, and a second
        # color up here would compete with it. The sentence sits *inside* the
        # freshness line, so it takes that line's ink and only its own weight.
        self.assertIn("ls-links__stalled", body)
        self.assertLess(body.index("ls-links__probe"),
                        body.index("ls-links__stalled"))
        self.assertLess(body.index("ls-links__stalled"),
                        body.index("ls-links__recheck"))

    def test_pressing_it_probes_and_redirects_back(self):
        with mock.patch.object(app_module.link_probe, "refresh_now") as press:
            response = self.client.post("/links/check", data={"next": "/links"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/links"))
        press.assert_called_once()

    def test_it_is_a_post_only_route(self):
        # A GET would let a reload, a prefetch or a crawler spend outbound
        # requests; the redirect is what stops a refresh from firing a second pass.
        self.assertEqual(self.client.get("/links/check").status_code, 405)

    def test_it_requires_a_login(self):
        response = app_module.app.test_client().post("/links/check")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_every_logged_in_viewer_may_press_it_not_only_an_admin(self):
        # Whoever maintains links.yaml is not necessarily an admin, and this is
        # the control that person needs most (ADR-0030).
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        with mock.patch.object(app_module.link_probe, "refresh_now") as press:
            response = self.client.post("/links/check", data={"next": "/links"})
        self.assertEqual(response.status_code, 302)
        press.assert_called_once()

    def test_the_return_path_cannot_become_an_open_redirect(self):
        with mock.patch.object(app_module.link_probe, "refresh_now"):
            response = self.client.post("/links/check",
                                        data={"next": "//evil.example.org/"})
        self.assertTrue(response.headers["Location"].endswith("/status"))

    def test_site_origin_keeps_only_the_origin(self):
        self.assertEqual(
            app_module._site_origin("https://a.example.org/deep/path?q=1"),
            "https://a.example.org")
        self.assertEqual(app_module._site_origin("not a url"), "")


class UserAvatarRouteTests(TestCase):
    """`/user/avatar` serves only the session user's selected file (ADR-0045)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def test_requires_login(self):
        response = self.client.get("/user/avatar")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_a_user_without_a_custom_avatar_gets_the_packaged_default(self):
        with mock.patch.dict(local_login.registered_avatars(), {}, clear=True):
            self._login()
            response = self.client.get("/user/avatar")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.headers["Location"].endswith("/static/default-avatar.svg"))

    def test_serves_the_session_users_custom_avatar_privately(self):
        with tempfile.TemporaryDirectory() as directory:
            picture = Path(directory) / "pan.png"
            picture.write_bytes(b"avatar-png")
            avatar = AvatarFile(path=picture, content_type="image/png",
                                root=Path(directory))
            with mock.patch.dict(local_login.registered_avatars(),
                                 {"pan": avatar}, clear=True):
                self._login()
                page = self.client.get("/status").get_data(as_text=True)
                response = self.client.get("/user/avatar")

            self.assertIn('src="/user/avatar"', page)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            self.assertEqual(response.data, b"avatar-png")
            self.assertIn("private", response.headers["Cache-Control"])
            self.assertTrue(response.headers.get("ETag"))

    def test_a_repeat_request_is_answered_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            picture = Path(directory) / "pan.webp"
            picture.write_bytes(b"avatar-webp")
            avatar = AvatarFile(path=picture, content_type="image/webp",
                                root=Path(directory))
            with mock.patch.dict(local_login.registered_avatars(),
                                 {"pan": avatar}, clear=True):
                self._login()
                first = self.client.get("/user/avatar")
                again = self.client.get(
                    "/user/avatar", headers={"If-None-Match": first.headers["ETag"]})

            self.assertEqual(again.status_code, 304)

    def test_a_selected_file_removed_while_running_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            picture = Path(directory) / "pan.png"
            picture.write_bytes(b"avatar-png")
            avatar = AvatarFile(path=picture, content_type="image/png",
                                root=Path(directory))
            with mock.patch.dict(local_login.registered_avatars(),
                                 {"pan": avatar}, clear=True):
                self._login()
                picture.unlink()
                response = self.client.get("/user/avatar")

            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                response.headers["Location"].endswith("/static/default-avatar.svg"))

    def test_a_selected_file_replaced_by_an_escaping_symlink_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            avatar_root = root / "avatars"
            avatar_root.mkdir()
            picture = avatar_root / "pan.png"
            picture.write_bytes(b"avatar-png")
            outside = root / "secret"
            outside.write_bytes(b"not-an-avatar")
            avatar = AvatarFile(path=picture.resolve(), content_type="image/png",
                                root=avatar_root.resolve())
            with mock.patch.dict(local_login.registered_avatars(),
                                 {"pan": avatar}, clear=True):
                self._login()
                picture.unlink()
                picture.symlink_to(outside)
                response = self.client.get("/user/avatar")

            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                response.headers["Location"].endswith("/static/default-avatar.svg"))

    def test_the_route_has_no_username_or_path_form(self):
        self._login()
        self.assertEqual(self.client.get("/user/avatar/pan").status_code, 404)


class LinkIconRouteTests(TestCase):
    """`/links/icon/<variant>/<name>` — every rung that holds bytes (ADR-0030)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def test_requires_login(self):
        response = self.client.get("/links/icon/on-light/grafana")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_serves_a_built_in_pair(self):
        self._login()
        for variant in ("on-light", "on-dark"):
            with self.subTest(variant=variant):
                response = self.client.get(f"/links/icon/{variant}/grafana")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "image/svg+xml")
                self.assertIn(b"<svg", response.data)
                self.assertIn("private", response.headers["Cache-Control"])
                self.assertTrue(response.headers.get("ETag"))

    def test_the_two_variants_carry_different_ink(self):
        self._login()
        light = self.client.get("/links/icon/on-light/grafana").data
        dark = self.client.get("/links/icon/on-dark/grafana").data
        self.assertNotEqual(light, dark)
        self.assertIn(b"#212529", light)
        self.assertIn(b"#e9edf1", dark)

    def test_a_repeat_request_is_answered_not_modified(self):
        self._login()
        first = self.client.get("/links/icon/on-light/aws")
        again = self.client.get("/links/icon/on-light/aws",
                                headers={"If-None-Match": first.headers["ETag"]})
        self.assertEqual(again.status_code, 304)

    def test_an_unknown_variant_is_not_found(self):
        self._login()
        self.assertEqual(
            self.client.get("/links/icon/sideways/grafana").status_code, 404)

    def test_an_undefined_name_is_not_found(self):
        self._login()
        self.assertEqual(
            self.client.get("/links/icon/on-light/cyberchef").status_code, 404)

    def test_a_name_cannot_walk_out_of_the_tree(self):
        # The name is a registry key, never a path — so this is a miss, not a read.
        self._login()
        for name in ("..%2f..%2fetc%2fpasswd", "....//etc/passwd", "%2e%2e"):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get(f"/links/icon/on-light/{name}").status_code, 404)

    def test_a_suppressed_name_is_not_found(self):
        self._login()
        icon = links.Icon(name="aws", suppressed=True)
        with mock.patch.object(app_module, "current_links",
                               return_value=links.LinksConfig(icons={"aws": icon})):
            self.assertEqual(
                self.client.get("/links/icon/on-light/aws").status_code, 404)

    def test_a_remote_icon_is_never_proxied(self):
        # It is emitted as its own URL; serving it from here would make this
        # instance fetch whatever a config file names.
        self._login()
        icon = links.Icon(name="jenkins",
                          on_light=links.IconFile(url="https://ci.example.org/i.svg"))
        with mock.patch.object(
                app_module, "current_links",
                return_value=links.LinksConfig(icons={"jenkins": icon})):
            self.assertEqual(
                self.client.get("/links/icon/on-light/jenkins").status_code, 404)

    def test_a_deployment_file_is_served_with_its_own_type(self):
        self._login()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "phoenix.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            icon = links.Icon(name="phoenix", on_light=links.IconFile(path=path),
                              on_dark=links.IconFile(path=path))
            with mock.patch.object(
                    app_module, "current_links",
                    return_value=links.LinksConfig(icons={"phoenix": icon})):
                response = self.client.get("/links/icon/on-light/phoenix")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/png")
            self.assertEqual(response.data, b"\x89PNG\r\n\x1a\n")

    def test_a_file_that_vanished_is_not_found(self):
        self._login()
        with tempfile.TemporaryDirectory() as directory:
            icon = links.Icon(
                name="gone",
                on_light=links.IconFile(path=Path(directory) / "gone.svg"))
            with mock.patch.object(
                    app_module, "current_links",
                    return_value=links.LinksConfig(icons={"gone": icon})):
                self.assertEqual(
                    self.client.get("/links/icon/on-light/gone").status_code, 404)


class SettingResolutionTests(TestCase):
    """SECRET_KEY / LITTLE_SISTER_API_TOKENS at startup (ADR-0023)."""

    def setUp(self):
        for patcher in (mock.patch.dict(os.environ),
                        mock.patch.dict(secrets._resolvers)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)

    def _noted(self, slug):
        found = [line for line in self_report.startup.lines() if line.slug == slug]
        self.assertEqual(len(found), 1, [line.slug for line in
                                         self_report.startup.lines()])
        return found[0]

    def test_unset_secret_key_gets_a_random_per_start_key(self):
        os.environ.pop("SECRET_KEY", None)
        key = app_module._session_key()
        self.assertEqual(len(key), 64)                      # token_hex(32)
        self.assertNotEqual(key, "dev-insecure-key-change-me")
        self.assertNotEqual(key, app_module._session_key())  # random each time

    def test_explicit_secret_key_wins(self):
        os.environ["SECRET_KEY"] = "keep-my-sessions"
        self.assertEqual(app_module._session_key(), "keep-my-sessions")

    def test_secret_key_may_be_a_reference(self):
        secrets.register_resolver("fake", lambda address: f"key:{address}")
        os.environ["SECRET_KEY"] = "fake://app/session-key"
        self.assertEqual(app_module._session_key(), "key:app/session-key")

    def test_failing_secret_key_reference_degrades_to_random(self):
        def failing(address: str) -> str:
            raise RuntimeError("store unreachable")
        secrets.register_resolver("fake", failing)
        os.environ["SECRET_KEY"] = "fake://app/session-key"
        with self.assertLogs("little_sister", level="WARNING") as caught:
            key = app_module._session_key()
        self.assertEqual(len(key), 64)
        # …and says so where somebody looks, not only in the log (backlog #70):
        # a standing note, WARN, for the life of the process.
        line = self._noted("secret-key")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertIn("every session ends at the next restart", line.text)
        self.assertIn("store unreachable", line.text)
        self.assertIn("secret-key: the SECRET_KEY reference did not resolve",
                      caught.output[0])

    def test_malformed_secret_key_reference_fails_loudly(self):
        os.environ["SECRET_KEY"] = "nope://app/session-key"
        with self.assertRaises(secrets.UnknownSchemeError):
            app_module._session_key()

    def test_api_tokens_literal_passes_through(self):
        os.environ["LITTLE_SISTER_API_TOKENS"] = "app=s3cret"
        self.assertEqual(app_module._api_token_setting(), "app=s3cret")

    def test_api_tokens_may_be_a_reference(self):
        secrets.register_resolver("fake", lambda address: "app=fr0m-store")
        os.environ["LITTLE_SISTER_API_TOKENS"] = "fake://app/tokens"
        self.assertEqual(app_module._api_token_setting(), "app=fr0m-store")

    def test_failing_api_token_reference_fails_closed(self):
        def failing(address: str) -> str:
            raise RuntimeError("store unreachable")
        secrets.register_resolver("fake", failing)
        os.environ["LITTLE_SISTER_API_TOKENS"] = "fake://app/tokens"
        self.assertEqual(app_module._api_token_setting(), "")
        line = self._noted("api-tokens")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertIn("the JSON API rejects every request", line.text)


if __name__ == "__main__":
    unittest.main()


class CodedReasonLineTests(TestCase):
    """Coded entry lines on the web surfaces (ADR-0042): the entry's own state
    class, the labeled cue (a line has no status word), and `is-running` as
    display — on the grid and on the leaf detail page alike."""

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert(
            "/ci/actions", StatusCode.ERROR,
            [Entry("build", "web (main) / build: failed after 8m14s · #4216 "
                           "running 2m", StatusCode.ERROR, running=True),
             Entry("test", "tests: passed in 2m01s", StatusCode.OK)])

    def tearDown(self):
        app_module.status_tree = self._original

    def test_the_grid_paints_the_line_not_the_node(self):
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("is-coded s-error", body)
        self.assertIn("is-running", body)
        # the passed line paints the pale ok tint — green under a red card
        # is the point of coded entries
        self.assertIn("is-coded s-ok", body)

    def test_the_line_cue_is_its_accessible_name(self):
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('aria-label="error"', body)
        self.assertIn('aria-label="ok"', body)

    def test_the_leaf_page_carries_the_same_channels(self):
        body = self.client.get("/status/ci/actions").get_data(as_text=True)
        self.assertIn("is-coded s-error", body)
        self.assertIn("is-coded s-ok", body)
        self.assertIn("is-running", body)
        self.assertIn('aria-label="error"', body)

    def test_a_pinned_coded_line_reads_quiet_and_keeps_its_cue(self):
        self.tree.set_entry_maintenance(
            "/ci/actions", "build", "rerunning",
            expires_at=datetime.now() + timedelta(days=1), set_by="pan",
            expected_set_at=None)
        # the node now reads OK, so the grid collapses it to a chip — the
        # leaf page is where every line always renders (ADR-0036)
        body = self.client.get("/status/ci/actions").get_data(as_text=True)
        self.assertIn("is-coded s-error is-running is-quiet", body)



def _record_rows(body: str) -> list[tuple[str, str]]:
    """Every name and value the page's record lists show, as a reader reads them:
    the text of each ``<dt>`` and of the ``<dd>`` beside it, in page order, with
    the tags stripped and the entities unescaped."""
    rows: list[tuple[str, str]] = []
    for block in re.findall(r'<dl class="reason-record[^"]*">(.*?)</dl>', body,
                            re.S):
        for name, value in re.findall(r"<dt>(.*?)</dt><dd>(.*?)</dd>", block,
                                      re.S):
            rows.append((html.unescape(re.sub(r"<[^>]+>", "", name)),
                         html.unescape(re.sub(r"<[^>]+>", "", value))))
    return rows


class RecordTimeTests(TestCase):
    """A record's times on its node's page: the names the seam types — `at`,
    `started` and `ended`, at any depth (ADR-0082 decision 2) — read in the
    configured timezone and `time_format`, and every other value is shown as it
    was stored. The values are the ones the plan's sentences are about: the UTC
    string a Lambda function's line in `little-sister-aws` shows today, and a
    batch job's nested `created.at`."""

    #: A Lambda function's own time, as the seam stores it.
    STORED = "2026-09-22T10:38:00Z"

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        # The configuration the sentences are read against, stated rather than
        # inherited: Berlin is on summer time in September, so 10:38 UTC is 12:38.
        settings = self._settings("Europe/Berlin", "%Y-%m-%d %H:%M:%S")
        settings.start()
        self.addCleanup(settings.stop)

    def tearDown(self):
        app_module.status_tree = self._original

    @staticmethod
    def _settings(zone: str, fmt: str):
        # `local_time` reads the configuration at the call, from its module
        return mock.patch("little_sister.config.config",
                          replace(app_module.config, timezone=zone,
                                  time_format=fmt))

    def _page(self, data: dict) -> str:
        """The page of a node whose one line carries ``data`` — a Lambda
        function's line, as `little-sister-aws` writes it."""
        self.tree.upsert("/aws/lambda", StatusCode.OK, [
            Entry("resize-images", "resize-images: no errors, last run 2h ago",
                  StatusCode.OK, subject="resize-images", data=data),
        ], members=True)
        response = self.client.get("/status/aws/lambda")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_a_carried_lines_time_reads_in_the_configured_zone(self):
        body = self._page({"name": "resize-images", "errors": 0,
                           "at": self.STORED})
        self.assertEqual(_record_rows(body),
                         [("name", "resize-images"), ("errors", "0"),
                          ("at", "2026-09-22 12:38:00")])
        # what was stored stays in the page, as the instant's machine form
        self.assertIn('<dt>at</dt><dd><time datetime="2026-09-22T10:38:00Z">'
                      '2026-09-22 12:38:00</time></dd>', body)

    def test_the_zone_and_the_format_are_the_configured_ones(self):
        with self._settings("America/New_York", "%d.%m.%Y %H:%M"):
            body = self._page({"at": self.STORED})
        self.assertEqual(_record_rows(body), [("at", "22.09.2026 06:38")])

    def test_a_nested_created_at_reads_in_the_configured_zone_too(self):
        # a batch job's run, as `little-sister-aws` keeps it: its creation
        # nested under `created`, its own times at the top
        body = self._page({"queue": "nightly", "name": "reindex",
                           "created": {"at": "2026-09-22T10:38:00Z"},
                           "started": "2026-09-22T10:40:00Z",
                           "ended": "2026-09-22T11:05:00Z",
                           "at": "2026-09-22T11:05:00Z"})
        self.assertEqual(_record_rows(body),
                         [("queue", "nightly"), ("name", "reindex"),
                          ("created.at", "2026-09-22 12:38:00"),
                          ("started", "2026-09-22 12:40:00"),
                          ("ended", "2026-09-22 13:05:00"),
                          ("at", "2026-09-22 13:05:00")])

    def test_every_name_the_seam_types_reads_as_an_instant(self):
        # the page reads the seam's own list, so the two cannot disagree about
        # which names are times
        for name in sorted(RECORD_TIMESTAMP_KEYS):
            with self.subTest(name=name):
                self.assertEqual(_record_rows(self._page({name: self.STORED})),
                                 [(name, "2026-09-22 12:38:00")])

    def test_a_value_under_any_other_name_is_shown_as_it_was_stored(self):
        # the type is the name's, never the value's: a time-shaped string under
        # a name the seam does not type stays as the check wrote it, and so does
        # a list, times inside it included
        body = self._page({"deadline": self.STORED, "errors": 0,
                           "log_note": None, "retried": True,
                           "runs": [{"at": self.STORED}]})
        self.assertEqual(_record_rows(body),
                         [("deadline", "2026-09-22T10:38:00Z"), ("errors", "0"),
                          ("log_note", "null"), ("retried", "true"),
                          ("runs", '[{"at": "2026-09-22T10:38:00Z"}]')])

    def test_a_null_under_a_timed_name_is_shown_as_it_was_stored(self):
        # *this run has not ended*: the seam keeps the null, and the page says
        # what the record holds
        body = self._page({"started": "2026-09-22T10:40:00Z", "ended": None})
        self.assertEqual(_record_rows(body),
                         [("started", "2026-09-22 12:40:00"), ("ended", "null")])

    def test_a_time_the_zone_cannot_hold_is_shown_as_it_was_stored(self):
        # the seam accepts any instant UTC can hold, and the last half hour of
        # the year 9999 in UTC is the year 10000 in Berlin
        body = self._page({"at": "9999-12-31T23:30:00Z"})
        self.assertEqual(_record_rows(body), [("at", "9999-12-31T23:30:00Z")])

    def test_so_is_one_before_the_first_year_in_the_zone(self):
        # the other edge: the first half hour of the year 1 in UTC is the year 0
        # in New York
        with self._settings("America/New_York", "%Y-%m-%d %H:%M:%S"):
            body = self._page({"at": "0001-01-01T00:30:00Z"})
        self.assertEqual(_record_rows(body), [("at", "0001-01-01T00:30:00Z")])

    def test_what_is_not_a_time_with_an_offset_is_shown_as_it_was_stored(self):
        # the seam lets none of these through, and the page does not guess: a
        # naive stamp is an instant only to whoever wrote it
        body = self._page({"at": "2026-09-22T10:38:00", "started": "soon",
                           "ended": 1758537480})
        self.assertEqual(_record_rows(body),
                         [("at", "2026-09-22T10:38:00"), ("started", "soon"),
                          ("ended", "1758537480")])

    def test_the_measured_record_reads_its_times_the_same_way(self):
        # the node's own record goes through the same filter and the same macro
        self.tree.upsert("/web/shop", StatusCode.OK, "200 in 412 ms",
                         subject="https://shop.example",
                         record={"status": 200, "response_ms": 412,
                                 "at": self.STORED})
        body = self.client.get("/status/web/shop").get_data(as_text=True)
        self.assertIn("Measured", body)
        self.assertEqual(_record_rows(body),
                         [("status", "200"), ("response_ms", "412"),
                          ("at", "2026-09-22 12:38:00")])


class TopmostTimeTests(TestCase):
    """The observation time shows on the topmost node visible in the current view
    and is suppressed below where it would be identical (ADR-0044; ADR-0027 as
    amended). Counts are asserted rather than digits, so the tests hold in any
    timezone; identical stored stamps render identically wherever they land."""

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _stamp(self, path, iso):
        node = self.tree._find_node(path)
        assert node is not None
        node.timestamp = iso

    def test_the_branch_head_shows_the_time_and_identical_cards_suppress(self):
        # A written sole-check container viewed as a branch: the head is the
        # topmost visible node, so it carries the run time once and the aspect
        # cards below — same check, same run — stay bare rather than repeating
        # it three times as if three checks had run.
        self.tree.set_check_mount("/quality/github")
        self.tree.upsert("/quality/github", StatusCode.OK)
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        self.tree.upsert("/quality/github/issues", StatusCode.OK)
        for path in ("/quality/github", "/quality/github/actions",
                     "/quality/github/issues"):
            self._stamp(path, "2026-08-06T11:30:01")
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)

    def test_a_run_crossing_a_minute_is_shown_rather_than_hidden(self):
        # DELIBERATELY ADJUSTED with the minute-precision display (times carry
        # no seconds — they saved no information worth the row width).
        # Suppression compares the *displayed* rendering: a child stamped in
        # the next displayed minute is not identical, so it shows — while one
        # a second later renders the same "11:30" and suppresses.
        self.tree.set_check_mount("/quality/github")
        self.tree.upsert("/quality/github", StatusCode.OK)
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        self.tree.upsert("/quality/github/issues", StatusCode.OK)
        self._stamp("/quality/github", "2026-08-06T11:30:59")
        self._stamp("/quality/github/actions", "2026-08-06T11:31:01")
        self._stamp("/quality/github/issues", "2026-08-06T11:30:58")
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 2)

    def test_a_sole_check_box_shows_its_time_under_an_ambiguous_card(self):
        # Two checks under /quality: the card has no single answer and shows
        # nothing (ADR-0027), while each nested sole-check container finally
        # states when its own check ran — the topmost visible carrier is the box.
        self.tree.set_check_mount("/quality/github")
        self.tree.set_check_mount("/quality/wiz")
        self.tree.upsert("/quality/github", StatusCode.ERROR, "boom")
        self.tree.upsert("/quality/github/actions", StatusCode.ERROR, "boom")
        self.tree.upsert("/quality/wiz", StatusCode.OK)
        self.tree.upsert("/quality/wiz/findings", StatusCode.OK)
        for path in ("/quality/github", "/quality/github/actions"):
            self._stamp(path, "2026-08-06T11:30:01")
        for path in ("/quality/wiz", "/quality/wiz/findings"):
            self._stamp(path, "2026-08-06T11:31:02")
        body = self.client.get("/status").get_data(as_text=True)
        # one per container box (a quiet *branch* stays a box, not a chip); the
        # identically-stamped grandchildren suppress under each
        self.assertEqual(body.count('class="status-card__time"'), 2)

    def test_a_box_under_a_timed_card_suppresses_the_identical_time(self):
        # A sole-check card shows the time; the box below it — same check, same
        # run — does not repeat it.
        self.tree.set_check_mount("/site/host")
        self.tree.upsert("/site/host", StatusCode.ERROR, "boom")
        self.tree.upsert("/site/host/disk", StatusCode.ERROR, "full")
        self._stamp("/site/host", "2026-08-06T11:30:01")
        self._stamp("/site/host/disk", "2026-08-06T11:30:01")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)

    def test_a_shared_two_check_mount_no_longer_times_its_card(self):
        # ADR-0044, which amends ADR-0027: two checks writing one mount leave
        # the unwritten card above them bare — a single inherited value would
        # present one check's run time as both checks'. The mount's own box
        # still shows its own last write.
        self.tree.set_check_mount("/shared/host")
        self.tree.set_check_mount("/shared/host")
        self.tree.upsert("/shared/host", StatusCode.ERROR, "boom")
        self._stamp("/shared/host", "2026-08-06T11:30:01")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)


class RunArrowTests(TestCase):
    """The next update joins the check time wherever that time shows (ADR-0044
    decision 5): `22:25:33 → 22:30` — absolute, seconds dropped on the arrow's
    side, kept when the two share a minute. Assertions target the arrow and its
    precision rather than digits, so they hold in any timezone (an offset moves
    both stamps together)."""

    ARROW = " → "

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _stamp(self, path, iso):
        node = self.tree._find_node(path)
        assert node is not None
        node.timestamp = iso

    def _minutes(self, body):
        """The rendered arrow sides, `→ HH:MM`-shaped (no seconds)."""
        return re.findall(r"→ \d\d:\d\d(?!:)", body)

    def _seconds(self, body):
        """The rendered arrow sides that kept their seconds."""
        return re.findall(r"→ \d\d:\d\d:\d\d", body)

    def test_the_branch_head_gains_the_next_update(self):
        self.tree.set_check_mount("/quality/github")
        self.tree.upsert("/quality/github", StatusCode.OK)
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        for path in ("/quality/github", "/quality/github/actions"):
            self._stamp(path, "2026-08-06T11:30:01")
        self.tree.set_run_facts("/quality/github", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        # the head's one time span carries the arrow, minute-precision
        self.assertEqual(body.count('class="status-card__time"'), 1)
        self.assertEqual(len(self._minutes(body)), 1)
        self.assertEqual(self._seconds(body), [])

    def test_an_inheriting_card_carries_it_and_the_box_suppresses(self):
        # The unwritten /site card inherits stamp *and* facts from its sole
        # mount below; the mount's own box — same run — repeats neither.
        self.tree.set_check_mount("/site/host")
        self.tree.upsert("/site/host", StatusCode.ERROR, "boom")
        self.tree.upsert("/site/host/disk", StatusCode.ERROR, "full")
        self._stamp("/site/host", "2026-08-06T11:30:01")
        self._stamp("/site/host/disk", "2026-08-06T11:30:01")
        self.tree.set_run_facts("/site/host", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)
        self.assertEqual(len(self._minutes(body)), 1)

    def test_sole_check_boxes_carry_their_own_arrows(self):
        # Two checks under /quality: the ambiguous card shows nothing, each
        # sole-check box shows its own time with its own next update.
        self.tree.set_check_mount("/quality/github")
        self.tree.set_check_mount("/quality/wiz")
        self.tree.upsert("/quality/github", StatusCode.ERROR, "boom")
        self.tree.upsert("/quality/github/actions", StatusCode.ERROR, "boom")
        self.tree.upsert("/quality/wiz", StatusCode.OK)
        self.tree.upsert("/quality/wiz/findings", StatusCode.OK)
        for path in ("/quality/github", "/quality/github/actions"):
            self._stamp(path, "2026-08-06T11:30:01")
        for path in ("/quality/wiz", "/quality/wiz/findings"):
            self._stamp(path, "2026-08-06T11:31:02")
        self.tree.set_run_facts("/quality/github", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")
        self.tree.set_run_facts("/quality/wiz", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:36:00")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 2)
        self.assertEqual(len(self._minutes(body)), 2)

    def test_no_facts_no_arrow(self):
        self.tree.set_check_mount("/site/host")
        self.tree.upsert("/site/host", StatusCode.ERROR, "boom")
        self._stamp("/site/host", "2026-08-06T11:30:01")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)
        self.assertNotIn(self.ARROW, body)

    def test_a_shared_mount_shows_a_bare_time(self):
        # Facts were written for the path, and the count keeps them off the
        # snapshot: the shared node's own last write answers for itself (rule
        # 2), but its next update would be one check's claim on both.
        self.tree.set_check_mount("/shared/host")
        self.tree.set_check_mount("/shared/host")
        self.tree.upsert("/shared/host", StatusCode.ERROR, "boom")
        self._stamp("/shared/host", "2026-08-06T11:30:01")
        self.tree.set_run_facts("/shared/host", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)
        self.assertNotIn(self.ARROW, body)

    def test_a_same_minute_next_update_is_suppressed(self):
        # DELIBERATELY ADJUSTED with the minute-precision display: an arrow to
        # the very value beside it (`11:30 → 11:30`) says nothing, so a
        # sub-minute next update shows a bare time instead — the arrow appears
        # exactly when it adds information.
        self.tree.set_check_mount("/quality/github")
        self.tree.upsert("/quality/github", StatusCode.OK)
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        for path in ("/quality/github", "/quality/github/actions"):
            self._stamp(path, "2026-08-06T11:30:01")
        self.tree.set_run_facts("/quality/github", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:30:31")
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        self.assertEqual(body.count('class="status-card__time"'), 1)
        self.assertEqual(self._minutes(body) + self._seconds(body), [])

    def test_the_leaf_page_says_the_next_update(self):
        # DELIBERATELY REWRITTEN with the node-facts block (ADR-0044 decision 8):
        # the leaf page used to carry the grid's `→ 11:35` suffix inside its
        # observation sentence; the Time card now states the next update on its
        # own line, so the arrow is the *grid's* form and saying both would say
        # it twice. The fact under test is unchanged — this page names the check,
        # so this page carries its next update.
        self.tree.set_check_mount("/site/disk")
        self.tree.upsert("/site/disk", StatusCode.OK)
        self._stamp("/site/disk", "2026-08-06T11:30:01")
        self.tree.set_run_facts("/site/disk", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")
        body = self.client.get("/status/site/disk").get_data(as_text=True)
        # The page's own full-precision format, not the grid's trimmed one: the
        # observation sentence directly above uses it, and two times a reader is
        # meant to compare should not be printed two ways.
        self.assertRegex(body, r"Next update \d{4}-\d\d-\d\d \d\d:35:00")
        self.assertEqual(self._minutes(body) + self._seconds(body), [])

    def test_a_leaf_below_a_branch_mount_stays_bare_on_its_page(self):
        # Its next update lives one level up, where the check is named.
        self.tree.set_check_mount("/quality/github")
        self.tree.upsert("/quality/github", StatusCode.OK)
        self.tree.upsert("/quality/github/actions", StatusCode.OK)
        for path in ("/quality/github", "/quality/github/actions"):
            self._stamp(path, "2026-08-06T11:30:01")
        self.tree.set_run_facts("/quality/github", wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")
        body = self.client.get(
            "/status/quality/github/actions").get_data(as_text=True)
        self.assertEqual(self._minutes(body) + self._seconds(body), [])


class CardStatusLineStyleTests(TestCase):
    """settings.yaml `card_status_line` reaches the page as a body attribute the
    stylesheet branches on: `below` opts the deployment into the standing
    second head line; the compact default renders no attribute at all, so an
    unconfigured deployment's markup is byte-for-byte what it was."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def test_the_default_renders_no_attribute(self):
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("data-ls-card-state", body)

    def test_below_lands_on_the_body(self):
        patched = replace(app_module.config, card_status_line="below")
        with mock.patch.object(app_module, "config", patched):
            body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-ls-card-state="below"', body)
        self.assertNotIn("Next update", body)


class NodeFactsTests(TestCase):
    """The shared node-facts block (ADR-0044 decision 8, questions §4.8): time,
    `report` and `config` in one partial, rendered by the leaf page and — for the
    first time — by the branch page, so a container stops being the one node whose
    stored text nothing renders."""

    HEADINGS = ("Time", "Report", "Configuration")

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _container(self, path="/quality/github"):
        """A sole-check branch container with text and run facts of its own."""
        self.tree.set_check_mount(path)
        self.tree.upsert(path, StatusCode.OK,
                         config="- **scope:** org", report="- alpha\n- beta",
                         frequency_seconds=300)
        self.tree.upsert(path + "/actions", StatusCode.OK)
        self.tree.set_run_facts(path, wall_seconds=0.4,
                                next_run_at="2026-08-06T11:35:00")

    def test_the_branch_page_renders_the_block(self):
        self._container()
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        for heading in self.HEADINGS:
            with self.subTest(heading=heading):
                self.assertIn(f">{heading}</h3>", body)
        self.assertIn("Next update", body)
        self.assertIn("Last run took", body)
        self.assertIn("/history/quality/github", body)

    def test_a_node_with_a_period_still_says_it_is_checked(self):
        # The half of the rule that did not change (ADR-0081): a check *is* read
        # on its interval, so its page says so in the words it always used.
        self._container()
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        self.assertIn("Checked every 5m", body)
        self.assertNotIn("Goes stale after", body)

    def test_the_instances_own_node_says_how_fresh_it_promises_to_be(self):
        # `/little-sister/startup` rendered "Checked every 1s" beside
        # real checks whose identical line meant a subject had been read on that
        # period. Nothing is checked here at all — the lines are recorded state
        # read on the tick, and readiness measured its trust store once, at
        # startup — so the node carries no period and the page states the
        # freshness the server actually promises instead (ADR-0081).
        self.tree.upsert("/little-sister/startup", StatusCode.OK,
                         stale_after=31.0)
        body = self.client.get(
            "/status/little-sister/startup").get_data(as_text=True)
        self.assertNotIn("Checked every", body)
        self.assertIn("Goes stale after 31s", body)

    def test_the_block_is_inside_the_polled_fragment(self):
        # `report` is an output of the run, so it changes every tick: outside
        # #status-grid it would be the one part of a polling page quietly going
        # stale. The fragment is what the poll swaps in, so it must carry it.
        self._container()
        frag = self.client.get(
            "/status/quality/github?fragment=1").get_data(as_text=True)
        self.assertIn(">Report</h3>", frag)
        self.assertIn("<li>alpha</li>", frag)

    def test_config_and_report_render_as_markdown(self):
        # Checks author both with `config_markdown()`; the leaf page rendered
        # config as literal pre-wrap text — a leftover from before the renderer
        # landed (ADR-0018), which showed `- **scope:** org` verbatim.
        self._container()
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        self.assertIn("<strong>scope:</strong>", body)
        self.assertNotIn("- **scope:** org", body)
        self.assertIn("<li>alpha</li>", body)

    def test_the_leaf_page_renders_the_same_block(self):
        self.tree.set_check_mount("/svc/api")
        self.tree.upsert("/svc/api", StatusCode.OK,
                         config="- **url:** http://x", report="- 3 endpoints")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        for heading in self.HEADINGS:
            with self.subTest(heading=heading):
                self.assertIn(f">{heading}</h3>", body)
        self.assertIn("<strong>url:</strong>", body)

    def test_the_report_never_reaches_the_grid(self):
        # Never on a card (ADR-0044 decision 6): volume is precisely what
        # `reason_cap` exists to keep off the dashboard.
        self._container()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("alpha", body)
        self.assertNotIn(">Report</h3>", body)

    def test_the_overview_root_gets_no_block(self):
        # The root is nobody's node: many checks, no single answer (rule 4).
        self._container()
        body = self.client.get("/status").get_data(as_text=True)
        for heading in self.HEADINGS:
            with self.subTest(heading=heading):
                self.assertNotIn(f">{heading}</h3>", body)

    def test_the_kiosk_keeps_none_of_it(self):
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self._container()
        body = self.client.get("/status/quality/github").get_data(as_text=True)
        for heading in self.HEADINGS:
            with self.subTest(heading=heading):
                self.assertNotIn(f">{heading}</h3>", body)

    def test_a_shared_container_shows_no_text_and_no_block(self):
        # Two checks on one node: the snapshot withholds the text and the run
        # facts (decision 1), and with nothing of its own to say the block does
        # not render at all — its Time card could only report "not yet observed"
        # about a node neither check writes.
        for _ in range(2):
            self.tree.set_check_mount("/system/node_a")
        self.tree.upsert("/system/node_a/disk", StatusCode.OK)
        body = self.client.get("/status/system/node_a").get_data(as_text=True)
        for heading in self.HEADINGS:
            with self.subTest(heading=heading):
                self.assertNotIn(f">{heading}</h3>", body)

    def test_a_written_shared_container_still_withholds_its_text(self):
        # Written by both checks and stamped, so the Time card has something to
        # say — but the text belongs to whoever owns the node alone, and nobody
        # does. The card renders; the two text blocks do not.
        for _ in range(2):
            self.tree.set_check_mount("/system/node_a")
        self.tree.upsert("/system/node_a", StatusCode.OK,
                         config="- **host:** a", report="- alpha")
        self.tree.upsert("/system/node_a/disk", StatusCode.OK)
        body = self.client.get("/status/system/node_a").get_data(as_text=True)
        self.assertIn(">Time</h3>", body)
        self.assertNotIn(">Report</h3>", body)
        self.assertNotIn(">Configuration</h3>", body)

    def test_a_pinned_unwritten_container_page_still_renders(self):
        # The 500 this slice found: a pin lands on a container no check wrote,
        # its history has a transition and no observation to bound it, and the
        # page now asks for exactly that period.
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self.tree.set_maintenance(
            "/system/alpha", "rebuild",
            expires_at=datetime.now() + timedelta(days=1), set_by="pan")
        response = self.client.get("/status/system/alpha")
        self.assertEqual(response.status_code, 200)
        history = self.client.get("/history/system/alpha")
        self.assertEqual(history.status_code, 200)


class ContainerHeadTests(TestCase):
    """The head of the page of a node that declares nothing of its own.

    A node that declares `UNDEFINED` is a container: the roll-up skips its code
    (ADR-0039), its card on the parent's page shows what it rolls up to, and a kept
    reading records the same (ADR-0087 decision 8). One that carries a sentence —
    the scope an `aws` check states above its accounts — headed its own page gray
    and *undefined*, the word hide-idle reads as never reported, while the dashboard
    drew the same node green. It heads with what its card shows now, and the Time
    card under it bounds no period of a status the node never had. A node that
    declares a code of its own heads with that code, as it always did.
    """

    SCOPE = "1 account, 1 account/region pair in scope"

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _estate(self, account=StatusCode.OK):
        """What the `aws` check writes: a root that declares nothing and states its
        scope, above an account that reports."""
        self.tree.set_check_mount("/cloud/aws")
        self.tree.upsert("/cloud/aws", StatusCode.UNDEFINED, self.SCOPE)
        self.tree.upsert("/cloud/aws/live", account)

    def _page(self, branch="cloud/aws"):
        return self.client.get(f"/status/{branch}").get_data(as_text=True)

    def _head(self, branch="cloud/aws"):
        """The head's classes, its cue's code and its status word."""
        head = self._page(branch).split('class="status-node viewed-head ', 1)[1]
        cue = re.search(r"status-cue--([a-z]+)", head)
        word = re.search(r'viewed-head__state">'
                         r'(?:<span class="status-card__time">[^<]*</span>)?'
                         r"([a-z]+)", head)
        assert cue is not None and word is not None
        return head.split('"', 1)[0], cue.group(1), word.group(1)

    def test_a_node_that_declares_nothing_heads_with_what_it_rolls_up_to(self):
        self._estate()
        self.assertEqual(self._head(), ("s-ok dim", "ok", "ok"))
        self.assertIn(self.SCOPE, self._page())

    def test_a_red_account_turns_the_head_red_and_pale(self):
        # Pale, as the node's card on the dashboard is: the color is its
        # account's, and the account is right below it, vivid — the culprit.
        self._estate(StatusCode.ERROR)
        self.assertEqual(self._head(), ("s-error dim", "error", "error"))

    def test_with_every_account_pinned_the_head_reads_maintenance(self):
        self._estate()
        self.tree.set_maintenance(
            "/cloud/aws/live", "cutover",
            expires_at=datetime.now() + timedelta(days=1), set_by="pan")
        self.assertEqual(self._head(),
                         ("s-maintenance dim", "maintenance", "maintenance"))

    def test_with_nothing_below_reporting_it_still_says_undefined(self):
        # The roll-up of nothing is nothing: here the word is true, and it is
        # the node's own, so it is not pale.
        self._estate(StatusCode.UNDEFINED)
        self.assertEqual(self._head(), ("s-undefined", "undefined", "undefined"))

    def test_a_node_that_declares_a_code_heads_with_its_own(self):
        # Unchanged: a verdict of its own is what the head says, and the red child
        # right below it says the rest — the `github` check's coverage node.
        self.tree.set_check_mount("/quality/github")
        self.tree.upsert("/quality/github", StatusCode.OK, "3 repositories")
        self.tree.upsert("/quality/github/actions", StatusCode.ERROR, "red")
        self.assertEqual(self._head("quality/github"), ("s-ok", "ok", "ok"))

    def test_the_time_card_bounds_no_period_of_a_status_it_never_had(self):
        # A root that declared OK and declares nothing now — an `aws` check's,
        # across its conversion — has that transition in its log, and the card
        # bounded it as "Status undefined from … until …" under a green head.
        self._estate()
        self.tree.upsert("/cloud/aws", StatusCode.OK, self.SCOPE)
        self.tree.upsert("/cloud/aws", StatusCode.UNDEFINED, self.SCOPE)
        body = self._page()
        self.assertIn("Observed ", body)
        self.assertNotIn("Status <strong>", body)

    def test_a_leaf_that_declares_nothing_keeps_its_period(self):
        # A leaf's UNDEFINED is its own state — nothing reported — and it has a
        # period like any other.
        self.tree.upsert("/svc/api", StatusCode.OK)
        self.tree.upsert("/svc/api", StatusCode.UNDEFINED)
        body = self._page("svc/api")
        self.assertIn("Status <strong>undefined</strong>", body)


class BoxStateTests(TestCase):
    """A nested box ends its head line the way a card head does: a right-aligned
    state cluster of staleness, the topmost-visible time, and the status word —
    which a box used to lack, leaving its time dangling after the title and its
    problem cue carrying the only status channel."""

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _stamp(self, path, iso):
        node = self.tree._find_node(path)
        assert node is not None
        node.timestamp = iso

    def test_every_box_prints_its_status_word(self):
        # the error leaf box and the quiet branch box alike — a card says "ok"
        # on a healthy day and so does a box now (the quiet leaf stays a chip)
        self.tree.upsert("/host/disk", StatusCode.ERROR, "disk full")
        self.tree.upsert("/host/net", StatusCode.OK)
        self.tree.upsert("/host/net/ping", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        clusters = re.findall(r'status-node__state">.*?</button></span>', body)
        self.assertEqual(len(clusters), 2)
        self.assertTrue(any("error<button" in c for c in clusters))
        self.assertTrue(any("ok<button" in c for c in clusters))

    def test_a_pinned_box_says_maintenance_and_what_it_silences(self):
        # the cluster carries the same transform display a card does (ADR-0032
        # rule 5): the word, then the reported reading the pin is silencing.
        # A quiet *leaf* collapses to a chip, so the pinned node needs a child
        # to stay a box.
        self.tree.upsert("/host/disk", StatusCode.ERROR, "disk full")
        self.tree.upsert("/host/disk/smart", StatusCode.ERROR, "smart fail")
        self.tree.set_maintenance(
            "/host/disk", "planned",
            expires_at=datetime.now() + timedelta(hours=1), set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn(
            'maintenance <span class="status-reported">· error</span>', body)

    def test_the_time_sits_inside_the_cluster(self):
        # a sole-check box under an ambiguous two-check card: its topmost-visible
        # time and its word travel together at the row's end
        self.tree.set_check_mount("/quality/github")
        self.tree.set_check_mount("/quality/wiz")
        self.tree.upsert("/quality/github", StatusCode.ERROR, "boom")
        self.tree.upsert("/quality/wiz", StatusCode.OK)
        self.tree.upsert("/quality/wiz/findings", StatusCode.OK)
        self._stamp("/quality/github", "2026-08-06T11:30:01")
        self._stamp("/quality/wiz", "2026-08-06T11:31:02")
        self._stamp("/quality/wiz/findings", "2026-08-06T11:31:02")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count(
            'status-node__state"><span class="status-card__time">'), 2)


class ContentSecurityPolicyTests(TestCase):
    """The header on the wire, the readout on /system, and the report endpoint
    (ADR-0048)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _policy(self):
        """Re-assemble, the way app creation does, so a contribution this test made
        reaches the header — the module global is deliberately not recomputed per
        request."""
        return mock.patch.object(app_module, "csp_policy", csp.assemble(
            inline_scripts=app_module._inline_scripts()))

    def test_a_document_carries_the_report_only_header(self):
        self._login()
        response = self.client.get("/status")
        self.assertIn("default-src 'self'",
                      response.headers[app_module.CSP_HEADER])
        # Report-Only, so nothing is enforced by shipping it
        self.assertNotIn("Content-Security-Policy", response.headers)

    def test_the_login_page_carries_it_too(self):
        self.assertIn("script-src",
                      self.client.get("/login").headers[app_module.CSP_HEADER])

    def test_an_error_page_carries_it(self):
        # a 404 is still a document, and the one most likely to be reached by a URL
        # somebody else composed
        self.assertIn(app_module.CSP_HEADER, self.client.get("/nope").headers)

    def test_the_json_api_and_the_static_files_do_not(self):
        # the policy governs how a *document* may be built; on JSON or on a
        # stylesheet it is a header no browser consults
        with mock.patch.object(app_module, "api_tokens", {"tester": "tok"}):
            api = self.client.get("/status", headers={
                "Accept": "application/json", "Authorization": "Bearer tok"})
        self.assertEqual(api.status_code, 200)      # a real API answer, not a 401
        self.assertEqual(api.mimetype, "application/json")
        self.assertNotIn(app_module.CSP_HEADER, api.headers)
        asset = self.client.get("/static/js/prefs.js")
        self.assertEqual(asset.status_code, 200)
        self.assertNotIn(app_module.CSP_HEADER, asset.headers)

    def test_the_hash_covers_the_inline_script_the_page_actually_carries(self):
        # the point of folding the two copies into one partial: *this* is the
        # guarantee, and it would break silently if the hashed text ever drifted
        # from the rendered one
        for path in ("/login", "/status"):
            with self.subTest(path=path):
                if path == "/status":
                    self._login()
                response = self.client.get(path)
                body = response.get_data(as_text=True)
                script = re.search(r"<script>(.*?)</script>", body, re.DOTALL)
                self.assertIsNotNone(script)
                self.assertIn(csp.inline_hash(script.group(1)),
                              response.headers[app_module.CSP_HEADER])

    def test_no_page_carries_an_inline_handler_any_more(self):
        self._login()
        for path in ("/login", "/status", "/system", "/links", "/about"):
            with self.subTest(path=path):
                body = self.client.get(path).get_data(as_text=True)
                self.assertIsNone(re.search(r"\son[a-z]+\s*=\s*[\"']", body))

    def test_the_switches_and_the_menu_radios_submit_through_the_script(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        # four filters, six themes, three layouts
        self.assertEqual(body.count("data-ls-submit"), 13)
        self.assertIn("js/prefs.js", body)

    def test_each_preference_form_keeps_a_noscript_submit(self):
        self._login()
        body = self.client.get("/status").get_data(as_text=True)
        self.assertEqual(body.count("<noscript>"), 2)

    def test_system_prints_the_policy_and_who_asked_for_each_source(self):
        csp.allow("connect-src", "https://tickets.example.org", by="ls_tickets")
        self._login()
        with self._policy():
            body = self.client.get("/system").get_data(as_text=True)
        self.assertIn(app_module.CSP_HEADER, body)
        self.assertIn("<code>connect-src</code>", body)
        self.assertIn("https://tickets.example.org", body)
        self.assertIn("(ls_tickets)", body)
        self.assertIn(f"({csp.LIBRARY})", body)

    def test_system_needs_an_admin_like_the_rest_of_the_page(self):
        # the readout names a deployment's internal hosts; it inherits /system's gate
        self.assertEqual(self.client.get("/system").status_code, 302)

    def test_a_violation_report_is_logged_without_a_session(self):
        # a violation on the login page has no session, so this endpoint cannot have
        # a gate — it is bounded instead
        payload = ('{"csp-report": {"document-uri": "http://x/status",'
                   ' "effective-directive": "img-src",'
                   ' "blocked-uri": "https://evil.example/p.png"}}')
        with self.assertLogs("little_sister", level="WARNING") as logs:
            response = self.client.post(csp.REPORT_PATH, data=payload,
                                        content_type="application/csp-report")
        self.assertEqual(response.status_code, 204)
        logged = "\n".join(logs.output)
        self.assertIn("img-src", logged)
        self.assertIn("https://evil.example/p.png", logged)

    def test_a_reported_field_cannot_forge_a_second_log_line(self):
        # a blocked URI is whatever the page tried to load, and this endpoint has no
        # gate: a newline through it would write an arbitrary log record
        payload = ('{"csp-report": {"blocked-uri": "https://e/p.png\\n'
                   '2026-08-07 12:00:00 CRITICAL engine: DISK FAILURE"}}')
        with self.assertLogs("little_sister", level="WARNING") as logs:
            self.client.post(csp.REPORT_PATH, data=payload,
                             content_type="application/csp-report")
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn("\n", logs.output[0])
        self.assertIn("DISK FAILURE", logs.output[0])   # flattened, not dropped

    def test_the_deprecated_directive_field_is_still_read(self):
        # Safari sends only `violated-directive`; the report must not read as "?"
        payload = '{"csp-report": {"violated-directive": "script-src"}}'
        with self.assertLogs("little_sister", level="WARNING") as logs:
            self.client.post(csp.REPORT_PATH, data=payload,
                             content_type="application/csp-report")
        self.assertIn("script-src violated", logs.output[0])

    def test_a_payload_that_is_not_a_report_is_logged_and_shrugged_off(self):
        for payload in ("{}", "not json at all", '{"csp-report": 3}'):
            with self.subTest(payload=payload):
                with self.assertLogs("little_sister", level="WARNING"):
                    response = self.client.post(csp.REPORT_PATH, data=payload,
                                                content_type="application/csp-report")
                self.assertEqual(response.status_code, 204)

    def test_an_oversized_report_is_refused_unread(self):
        with self.assertLogs("little_sister", level="WARNING") as logs:
            response = self.client.post(
                csp.REPORT_PATH, data="x" * (app_module.CSP_REPORT_LIMIT + 1),
                content_type="application/csp-report")
        self.assertEqual(response.status_code, 204)
        self.assertIn("refused unread", "\n".join(logs.output))

    def test_an_oversized_body_is_refused_before_it_is_parsed(self):
        # the limit is a bounded *read*, not a Content-Length check — this is the one
        # route with no session behind it, and a chunked request carries no length to
        # measure. If the body reached the parser, this patch would say so.
        with mock.patch.object(app_module.json, "loads",
                               side_effect=AssertionError("parsed anyway")):
            with self.assertLogs("little_sister", level="WARNING"):
                response = self.client.post(
                    csp.REPORT_PATH,
                    data="x" * (app_module.CSP_REPORT_LIMIT * 4),
                    content_type="application/csp-report")
        self.assertEqual(response.status_code, 204)

    def test_a_reported_field_is_truncated_before_it_reaches_the_log(self):
        # a blocked URI is whatever the page tried to load, so it is untrusted text
        payload = ('{"csp-report": {"blocked-uri": "https://evil.example/'
                   + "a" * 500 + '"}}')
        with self.assertLogs("little_sister", level="WARNING") as logs:
            self.client.post(csp.REPORT_PATH, data=payload,
                             content_type="application/csp-report")
        self.assertNotIn("a" * (app_module.CSP_FIELD_LIMIT + 1),
                         "\n".join(logs.output))


class SystemPackagesTests(TestCase):
    """`/system`'s package inventory — what is installed beside the library.

    A package reaches an instance through five seams, and only the check-type
    roster ever carried an origin. An extension that registers no type — the Jira
    chip is exactly that shape — therefore had its *version* nowhere on the page.
    The secret resolvers joined them last (ADR-0064), and are also the one seam
    whose whole list is printed, built-in included.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        app_module.status_tree = StatusTree()
        self.client = app_module.app.test_client()
        self.addCleanup(slots.forget_fillers)
        self.addCleanup(forget_aspects)
        resolvers = mock.patch.dict(secrets._resolvers)
        resolvers.start()
        self.addCleanup(resolvers.stop)

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _system(self):
        app_module.engine = None
        return self.client.get("/system").get_data(as_text=True)

    def _register_a_surface_extension(self):
        """A filler and an aspect, the way a chip package registers: no check type.
        `tests.demo_extension` is the one package in the suite that really ships a
        templates/ directory, so the registration is not stubbed."""
        from tests.demo_extension import node_action
        slots.register("node.actions", "tests.demo_extension",
                       "node_action.html", node_action)
        register_aspect("jira")

    def test_a_package_with_no_check_type_still_reports_its_origin(self):
        self._login()
        self._register_a_surface_extension()

        body = self._system()

        self.assertIn("Packages", body)
        # keyed by the top-level package, not the template namespace the filler
        # was registered under — a version belongs to an installation
        self.assertIn("<code>tests</code>", body)
        self.assertIn("slot node.actions", body)
        self.assertIn("config/jira", body)
        # loaded from, so a copy on the path is visible as one
        self.assertRegex(body, r"tests/__init__\.py")
        # not installed as a distribution: said out loud rather than left blank
        self.assertIn("source", body)

    def test_a_registration_never_breaks_across_lines(self):
        # "slot reason.actions" wrapping after the word reads as two entries, and
        # the column is narrow enough for it. The class has to exist in the
        # stylesheet the page actually loads, or the markup says nothing.
        self._login()
        self._register_a_surface_extension()
        body = self._system()
        self.assertIn('<span class="ls-system__register">slot node.actions</span>',
                      body)
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        self.assertIn(".ls-system__register { white-space: nowrap; }", css)

    def test_a_package_path_is_drawn_against_a_root_too(self):
        # one rule in two places: this card and the check-type roster print the
        # same kind of path, so the shortening is a filter both use rather than a
        # fix in one template
        import sysconfig
        purelib = sysconfig.get_paths()["purelib"]
        absolute = str(Path(purelib) / "little_sister_jira" / "__init__.py")
        row = app_module.PackageRow(
            origin=origins.PackageOrigin(package="little_sister_jira",
                                         distribution="little-sister-jira",
                                         version="0.1.0", path=absolute),
            registers=("config/jira",))
        self._login()

        with mock.patch.object(app_module, "_registering_packages",
                               lambda: [row]):
            body = self._system()

        self.assertIn(f">{Path(purelib).name}/little_sister_jira/__init__.py"
                      "</small>", body)
        self.assertNotIn(f">{absolute}</small>", body)
        self.assertIn(f'title="{absolute}"', body)

    def test_the_library_is_not_one_of_the_packages(self):
        # the built-in check types would otherwise put little_sister in the table;
        # the page header already carries its version
        self._login()
        body = self._system()
        self.assertNotIn("<code>little_sister</code>", body)

    def test_the_card_is_absent_when_only_the_library_registered(self):
        # a deployment with no extensions gets no section rather than an empty one.
        # The registries are process-wide and other modules in this suite register
        # into them, so the empty case is staged rather than waited for.
        self._login()
        with mock.patch.object(app_module, "registered_types",
                               lambda: [origin for origin
                                        in registered_types() if origin.builtin]), \
             mock.patch.object(app_module.slots, "extension_fillers",
                               lambda: ()), \
             mock.patch.object(app_module.slots, "assets", lambda: ()), \
             mock.patch.object(app_module, "registered_aspects", lambda: ()):
            self.assertNotIn("Packages", self._system())

    def test_a_resolver_puts_its_package_in_the_inventory(self):
        # the fifth seam (ADR-0064): a scheme is where a credential is read from,
        # so which installation answers for it belongs beside the other four
        self._login()
        secrets.register_resolver("aws-sm-live", lambda address: "v")
        body = self._system()
        self.assertIn("<code>tests</code>", body)
        self.assertIn("secret aws-sm-live://", body)

    def test_the_library_s_own_scheme_adds_no_package_row(self):
        # `env` is the library's, and the page header already carries its version
        self._login()
        body = self._system()
        self.assertNotIn("<code>little_sister</code>", body)

    def test_a_self_report_contributor_puts_its_package_in_the_inventory(self):
        # the sixth seam (ADR-0071): a contributor is visible on the heartbeat
        # only while it has something to say, so the row is where a quiet one
        # can be seen to have registered at all
        from little_sister.self_report import register_contributor
        self._login()
        register_contributor("keeper", lambda: [])
        body = self._system()
        self.assertIn("<code>tests</code>", body)
        self.assertIn("report keeper", body)

    def _resolver_row(self, body: str, scheme: str, package: str,
                      replaces: str, origin: str) -> None:
        """Assert the whole four-cell row for `scheme`, in order.

        Whole row, not `assertIn` on a cell: the columns are what the table
        *means* — who answers, whom that displaced, and whether it is ours — and a
        per-cell assertion passes just as well when a value lands one column over.
        Whitespace is collapsed so the check does not pin the template's
        indentation, and the row is anchored at both ends by its own tags.
        """
        flat = re.sub(r"\s+", " ", body)
        self.assertIn(
            f"<td><code>{scheme}://</code></td> <td>{package}</td> "
            f'<td class="text-muted">{replaces}</td> '
            f'<td class="text-muted">{origin}</td>', flat)

    def test_a_scheme_claimed_by_nobody_joins_no_package_row(self):
        # a resolver registered from `__main__` names no installation, so there is
        # no row it could honestly join — the scheme table below still shows it
        self._login()
        secrets._resolvers["odd"] = secrets.Registration(
            scheme="odd", resolver=lambda address: "v", package="")
        body = self._system()
        self.assertNotIn("secret odd://", body)
        self._resolver_row(body, "odd", secrets.UNIDENTIFIED, "—", "extension")

    def test_the_scheme_table_names_who_answers_for_each_one(self):
        # "which schemes may I write here" and "whose code reads this credential"
        # are the two questions, and the second is why the owner is a column
        self._login()
        secrets.register_resolver("aws-sm-live", lambda address: "v")
        body = self._system()
        self.assertIn("<th>Scheme</th>", body)
        self._resolver_row(body, "aws-sm-live", "tests", "—", "extension")

    def test_the_scheme_table_is_shaped_like_the_slot_table(self):
        # one card, two seams, one shape — and `From` means the same thing in both,
        # so a reader learns the columns once
        self._login()
        body = self._system()
        self.assertIn("<tr><th>Slot</th><th>Package</th><th>Template</th>"
                      "<th>Context</th><th>From</th></tr>", body)
        self.assertIn("<tr><th>Scheme</th><th>Package</th><th>Replaces</th>"
                      "<th>From</th></tr>", body)

    def test_the_built_in_env_scheme_is_listed_too(self):
        # unlike the aspects line below: the schemes are additive and a reference
        # names exactly one, so the whole table is the answer — and leaving the
        # library's own claim out would make an override of it look ordinary
        self._login()
        self._resolver_row(self._system(), "env", "little_sister", "—",
                           "built-in")

    def test_a_replacement_says_whom_it_displaced(self):
        # the one fact the outcome cannot show: the page would otherwise say the
        # scheme is owned by whoever owns it, with nothing to say somebody else did
        self._login()
        secrets.register_resolver("env", lambda name: "from-the-store",
                                  replace=True)
        self._resolver_row(self._system(), "env", "tests", "little_sister",
                           "extension")

    def test_the_aspects_line_names_who_registered_each_one(self):
        # "is this file declared" is not the question when config/jira misbehaves
        self._login()
        self._register_a_surface_extension()
        body = self._system()
        self.assertIn("Registered configuration aspects", body)
        self.assertRegex(body, r"config/jira</code> \(tests\)")

    def test_a_registration_from_a_script_claims_nothing(self):
        # `__main__` is what any script is called when run directly, so it names no
        # installation and changes with the launcher; a deployment's `wsgi` module
        # keeps its name, because that one points at a file somebody can open
        module = {"__name__": "__main__"}
        with mock.patch.object(origins.sys, "_getframe",
                               return_value=mock.Mock(f_globals=module)):
            self.assertEqual(origins.calling_package(), "")
        module["__name__"] = "wsgi"
        with mock.patch.object(origins.sys, "_getframe",
                               return_value=mock.Mock(f_globals=module)):
            self.assertEqual(origins.calling_package(), "wsgi")

    def test_the_registrant_is_recorded_only_for_a_winning_registration(self):
        register_aspect("jira")
        self.assertEqual(aspect_owner("jira"), "tests")
        # a built-in may not be redefined, so nobody may claim it
        with self.assertLogs("little_sister", level="WARNING"):
            register_aspect("users")
        self.assertEqual(aspect_owner("users"), "")

        forget_aspects()

        self.assertEqual(aspect_owner("jira"), "")

    def test_package_origin_reads_the_installed_metadata(self):
        origin = package_origin("little_sister")

        self.assertEqual(origin.distribution, "little-sister")
        self.assertTrue(origin.version)
        self.assertTrue(origin.builtin)
        self.assertTrue(origin.path.endswith("little_sister/__init__.py"))

    def test_package_origin_of_something_not_installed(self):
        origin = package_origin("nothing_by_this_name")

        self.assertEqual((origin.distribution, origin.version, origin.path),
                         ("", "", ""))


class NodeCopyPageTests(TestCase):
    """The hand-off on a leaf's detail page: the same two buttons `/copy` has,
    aimed at one node."""

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _leaf(self, path="/svc/api"):
        self.tree.set_check_mount(path)
        self.tree.upsert(path, StatusCode.ERROR,
                         "connection refused to **api**",
                         frequency_seconds=900,
                         config="- **token:** env://API_TOKEN")

    def test_the_leaf_page_offers_both_formats(self):
        self._leaf()
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("Copy Markdown", body)
        self.assertIn("Copy Rich HTML", body)
        self.assertIn('id="ls-copy-source"', body)   # the manual-copy fallback
        self.assertIn('id="ls-copy-html"', body)     # the text/html member
        self.assertIn("js/copy.js", body)

    def test_the_source_carries_this_node_not_the_tree(self):
        self._leaf()
        self.tree.upsert("/other/thing", StatusCode.ERROR, "not my incident")

        body = self.client.get("/status/svc/api").get_data(as_text=True)

        self.assertIn("## api ⛔", body)
        self.assertIn("**Path:** /svc/api", body)
        self.assertIn("**Checked every:** 15m", body)
        self.assertIn("env://API_TOKEN", body)
        self.assertNotIn("not my incident", body)

    def test_a_container_gets_no_buttons(self):
        # A container's page is a dashboard *of its children*; the hand-off for a
        # subtree is `/copy`, and a second one here would mean two documents
        # answering the same question differently.
        self._leaf("/svc/api")
        body = self.client.get("/status/svc").get_data(as_text=True)
        self.assertNotIn("Copy Markdown", body)
        self.assertNotIn("Copy Rich HTML", body)
        self.assertNotIn("js/copy.js", body)

    def test_the_two_members_are_one_document(self):
        # The `text/html` member is rendered *from* the Markdown, never beside it,
        # so the two clipboard formats cannot drift (the `/copy` rule, one node
        # down). The payload is JSON-encoded, so its `<` are escaped there.
        self._leaf()
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        payload = re.search(
            r'<script type="application/json" id="ls-copy-html">(.*?)</script>',
            body, re.S)
        assert payload is not None
        document = json.loads(payload.group(1))
        self.assertIn("<h2>api ⛔</h2>", document)
        self.assertIn("<strong>api</strong>", document)   # the reason's Markdown
        self.assertNotIn("<script", payload.group(1))

    def test_the_payload_cannot_break_out_of_html_or_json(self):
        self.tree.upsert("/svc/api", StatusCode.ERROR,
                         "</textarea></script><script>BAD</script>")

        body = self.client.get("/status/svc/api").get_data(as_text=True)

        self.assertNotIn("<script>BAD</script>", body)
        self.assertNotIn("</textarea></script>", body)


class CopyRouteTests(TestCase):
    """One route, three documents (ADR-0036 decision 12's addressing): the tree,
    one node, one reason line."""

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _reviews(self):
        self.tree.upsert("/ci/reviews", StatusCode.ERROR, [
            Entry("pr-412", "acme/api-pr-412 review overdue"),
            Entry("pr-77", "acme/web-pr-77 review overdue"),
        ], members=True, config="- **token:** env://GITHUB_TOKEN")

    def _body(self, url):
        return self.client.get(url).get_data(as_text=True)

    def test_the_tree_document_is_still_at_copy(self):
        self._reviews()
        body = self._body("/copy")
        self.assertIn("Copy status", body)
        self.assertIn("reviews ⛔", body)
        self.assertIn("acme/web-pr-77", body)      # every line, this is the tree

    def test_a_node_document_has_a_url_of_its_own(self):
        self._reviews()
        body = self._body("/copy/ci/reviews")
        self.assertIn("**Path:** /ci/reviews", body)
        self.assertIn("acme/api-pr-412", body)
        self.assertIn("acme/web-pr-77", body)      # the node keeps every line
        self.assertIn("Configuration", body)

    def test_a_reason_document_carries_one_line(self):
        # The slug is a **query value**, never a path segment: a discovered entry's
        # slug contains a `/` and a percent-encoded one does not survive PATH_INFO
        # (ADR-0036 decision 12).
        self._reviews()
        body = self._body("/copy/ci/reviews?reason=pr-412")
        self.assertIn("**Path:** /ci/reviews", body)
        self.assertIn("acme/api-pr-412", body)
        self.assertNotIn("acme/web-pr-77", body)
        self.assertNotIn("Configuration", body)    # a node fact, not a finding's
        self.assertNotIn("GITHUB_TOKEN", body)

    def test_a_slug_with_a_slash_in_it_survives_the_round_trip(self):
        # Both spellings, because the two ends disagree and both are correct: a
        # slash is legal in a query string, so the chip's `url_for` emits it raw,
        # while a hand-written or copied URL may well carry it encoded.
        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"acme/api-pr-412": "review overdue"}, members=True)
        for url in ("/copy/ci/reviews?reason=acme%2Fapi-pr-412",
                    "/copy/ci/reviews?reason=acme/api-pr-412"):
            with self.subTest(url=url):
                self.assertIn("review overdue", self._body(url))

    def test_the_chip_emits_a_url_this_route_answers(self):
        # The end-to-end claim, rather than two halves that each look right: take
        # the href the page actually rendered and ask for it.
        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"acme/api-pr-412": "review overdue"}, members=True)
        chip = re.search(r'<a class="reason-action" href="([^"]+)"',
                         self._body("/status/ci/reviews"))
        assert chip is not None
        response = self.client.get(chip.group(1))
        self.assertEqual(response.status_code, 200)
        self.assertIn("review overdue", response.get_data(as_text=True))

    def test_a_line_this_run_does_not_report_is_not_invented(self):
        # Suspended, not deleted (ADR-0036 decision 6) — but there is no document
        # to make of a line that is not there, and the pin's stored text would be
        # a finding the check is no longer making.
        self._reviews()
        response = self.client.get("/copy/ci/reviews?reason=pr-999")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 404)
        self.assertIn("no longer reported", body)
        self.assertNotIn("acme/api-pr-412", body)

    def test_an_unmounted_path_is_a_404_with_a_page(self):
        response = self.client.get("/copy/nowhere/at/all")
        self.assertEqual(response.status_code, 404)
        self.assertIn("No such node", response.get_data(as_text=True))

    def test_every_document_is_auth_gated(self):
        self._reviews()
        anonymous = app_module.app.test_client()
        for url in ("/copy", "/copy/ci/reviews", "/copy/ci/reviews?reason=pr-412"):
            with self.subTest(url=url):
                response = anonymous.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.headers["Location"])


class CopyChipTests(TestCase):
    """The built-in copy chip in the `reason.actions` rail."""

    def setUp(self):
        self.tree = StatusTree()
        self._original = app_module.status_tree
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def tearDown(self):
        app_module.status_tree = self._original

    def _body(self, url):
        return self.client.get(url).get_data(as_text=True)

    def test_the_chip_links_each_member_line_to_its_own_document(self):
        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"pr-412": "review overdue", "pr-77": "review overdue"},
                         members=True)
        for url in ("/status/ci/reviews", "/status"):
            with self.subTest(surface=url):
                body = self._body(url)
                self.assertIn("/copy/ci/reviews?reason=pr-412", body)
                self.assertIn("/copy/ci/reviews?reason=pr-77", body)

    def test_prose_gets_no_chip(self):
        # Where reasons are prose there is one thing to hand over and it is the
        # node (ADR-0036): a per-line copy would offer half of one condition.
        self.tree.upsert("/svc/api", StatusCode.ERROR,
                         ["check error: boom", "Traceback..."])
        body = self._body("/status/svc/api")
        self.assertIn("check error: boom", body)
        self.assertNotIn("/copy/svc/api?reason=", body)

    def test_the_chip_addresses_a_slug_and_never_a_position(self):
        # ADR-0036 decision 3: an index moves when an entry is inserted above it.
        # Insert one and the chip must still point at the same finding.
        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"pr-412": "review overdue"}, members=True)
        first = self._body("/status/ci/reviews")
        self.assertIn("/copy/ci/reviews?reason=pr-412", first)

        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"pr-1": "newer, listed first",
                          "pr-412": "review overdue"}, members=True)
        second = self._body("/status/ci/reviews")

        self.assertIn("/copy/ci/reviews?reason=pr-412", second)
        self.assertIn("/copy/ci/reviews?reason=pr-1", second)

    def test_a_line_with_no_slug_of_its_own_gets_no_chip(self):
        # Belt and braces on the provider's own guard: a chip whose URL could not
        # name a line would be a link to the wrong document, so it declines.
        self.tree.upsert("/ci/reviews", StatusCode.ERROR,
                         {"pr-412": "review overdue"}, members=True)
        node = self.tree.snapshot("/ci/reviews")
        assert node is not None
        blank = replace(node.reasons[0], slug="")

        self.assertIsNone(copy_context(node=node, reason=blank.text, line=blank,
                                       index=0, surface="grid"))
        self.assertIsNone(copy_context(node=replace(node, path=""),
                                       reason=blank.text, line=node.reasons[0],
                                       index=0, surface="grid"))


class SystemPageDeclaredCostTests(TestCase):
    """`/system` shows what a check declared beside what its runs measured
    (ADR-0075). Rendered from the partial the page's poll re-fetches, with a real
    engine's `info()` behind it — the block is skipped entirely when no engine is
    running, which is how the page looks in this test module's own app."""

    def _info(self):
        from little_sister.checks.base import Check, CheckResult
        from little_sister.engine import Engine

        class _Declaring(Check):
            type_name = "declaring"

            def measure(self) -> Sequence[Measurement]:
                return ()

            def grade(self, measurements: Sequence[Measurement],
                      now: datetime) -> CheckResult:
                return CheckResult(StatusCode.OK)

            def expected_cost(self) -> float:
                return 90.0

            def expected_entries(self) -> int:
                return 1200

        class _Silent(_Declaring):
            type_name = "silent"

            def expected_cost(self) -> float | None:
                return None

            def expected_entries(self) -> int | None:
                return None

        checks = [_Declaring(path="/estate", frequency_seconds=900),
                  _Silent(path="/quiet", frequency_seconds=900)]
        return Engine(checks, StatusTree(), max_workers=4).info()

    def _render(self):
        from flask import render_template
        with app_module.app.test_request_context():
            return render_template("_system_info.html", info=self._info())

    def test_the_declared_sums_stand_beside_the_entries_held(self):
        body = self._render()
        self.assertIn("Declared load", body)
        self.assertIn("0.1", body)                      # 90 s every 15m
        # the pool is the roster's size, two, not the ceiling of four
        self.assertIn("of 2 worker threads", body)
        self.assertIn("1,200 declared", body)

    def test_a_check_that_declared_nothing_shows_nothing(self):
        # the last cell of the row is the declared one, and an em dash is the
        # whole of it — nothing declared is not the claim that nothing is spent
        row = self._render().split("/status/quiet")[1].split("</tr>")[0]
        self.assertEqual(row.rsplit("<td", 1)[1].split(">", 1)[1]
                         .replace("</td>", "").strip(), "—")

    def test_a_declaring_check_shows_both_figures(self):
        row = self._render().split("/status/estate")[1].split("</tr>")[0]
        self.assertIn("1m 30s", row)
        self.assertIn("1,200 entries", row)


def _reading_rows(body: str) -> list[list[str]]:
    """Every row of the page's readings tables, as a reader reads it: the text of
    each cell, the tags stripped and the entities unescaped, a cue read by its
    accessible name."""
    rows: list[list[str]] = []
    for table in re.findall(r'<table class="[^"]*\bls-readings\b[^"]*">(.*?)</table>',
                            body, re.S):
        body_part = table.split("<tbody>", 1)[1]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body_part, re.S):
            cells = []
            for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S):
                cue = re.search(r'aria-label="([^"]+)"', cell)
                text = html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()
                cells.append(cue.group(1) if cue and not text else text)
            rows.append(cells)
    return rows


def _curves(body: str) -> list[str]:
    """Each curve's SVG on the page, whole."""
    return re.findall(r'<svg class="ls-curve__plot".*?</svg>', body, re.S)


class SubjectSeriesTests(TestCase):
    """The node that stands for a subject shows its series (ADR-0092 decision 6),
    read against the plan's sentence for it: the check's page shows its newest
    readings and a response-time curve, a failed reading is a marked gap in it and a
    stretch without readings a plain one, and every kept reading is on its History
    page.

    The check is the plan's: an `http` check every three minutes that keeps a day
    of one site. Its series is written into the store the engine reads, the way
    the engine writes it, and the node is left as the newest run left it."""

    URL = "https://www.example.org"
    PATH = "/web/site"
    T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
    #: Twelve readings three minutes apart, the seventh a request that failed;
    #: then an hour in which nothing was read — the machine asleep — and three more.
    MINUTES = (0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 93, 96, 99)
    FAILED = 18

    def setUp(self):
        self.tree = StatusTree()
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        app_module.status_tree = self.tree
        settings = mock.patch(
            "little_sister.config.config",
            replace(app_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _restore(self):
        app_module.status_tree, app_module.engine = self._saved

    def _deploy(self, **config):
        """The check, its kept readings, and its node as the newest run left it."""
        from little_sister.checks.http import HttpCheck
        from little_sister.engine import Engine
        from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
        check = HttpCheck.from_config(
            {"type": "http", "path": self.PATH, "url": self.URL,
             "frequency": "3m", "series_keep": 480, **config}, Path("."))
        store = MemoryStore()
        for minute in self.MINUTES:
            failed = minute == self.FAILED
            response_ms = None if failed else 400 + minute
            record = ({"status": None, "response_ms": None, "error": "timed out"}
                      if failed else {"status": 200, "response_ms": response_ms})
            said = ("request failed: timed out" if failed
                    else f"HTTP 200 in {response_ms} ms")
            store.add(SeriesKey("http", self.PATH, self.URL),
                      SeriesRecord(record, self.T0 + timedelta(minutes=minute),
                                   code=StatusCode.ERROR if failed else StatusCode.OK,
                                   texts=(said,)),
                      keep=480)
        app_module.engine = Engine([check], self.tree, series=store)
        self.tree.upsert(self.PATH, StatusCode.OK,
                         [Entry("response", "HTTP 200 in 499 ms")],
                         frequency_seconds=180, subject=self.URL,
                         record={"status": 200, "response_ms": 499})
        return check

    def _page(self, path=None):
        response = self.client.get(f"/status{path or self.PATH}")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _time(self, minute):
        """A reading's time as the page writes it: Berlin, on summer time."""
        moment = self.T0 + timedelta(minutes=minute, hours=2)
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    def test_the_page_shows_a_response_time_curve(self):
        self._deploy()
        body = self._page()
        curve, = _curves(body)
        self.assertIn("Response time", body.split('<svg class="ls-curve__plot"')[0]
                      .rsplit('<figure class="ls-curve"', 1)[1])
        self.assertIn('role="img"', curve)
        self.assertIn(self._time(0), curve)       # the time axis, in Berlin
        self.assertIn(self._time(99), curve)

    def test_and_its_newest_readings_newest_first(self):
        self._deploy()
        rows = _reading_rows(self._page())
        self.assertEqual(len(rows), 10)           # reading_cap, 10 by default
        newest = sorted(self.MINUTES, reverse=True)[:10]
        self.assertEqual([row[0] for row in rows],
                         [self._time(minute) for minute in newest])

    def test_a_row_is_the_reading_as_it_stood(self):
        # the time on the series' clock, the code as a cue, a column per field as
        # the record list writes it, and the sentence
        self._deploy()
        body = self._page()
        self.assertIn('<th scope="col">status</th><th scope="col">response_ms</th>'
                      '<th scope="col">error</th>', body)
        rows = _reading_rows(body)
        self.assertEqual(rows[0], [self._time(99), "ok", "200", "499", "",
                                   "HTTP 200 in 499 ms"])
        failed, = (row for row in rows if row[0] == self._time(self.FAILED))
        self.assertEqual(failed, [self._time(self.FAILED), "error", "null", "null",
                                  "timed out", "request failed: timed out"])

    def test_a_failed_reading_is_a_marked_gap_in_it(self):
        self._deploy()
        curve, = _curves(self._page())
        self.assertEqual(
            len(re.findall(r'<line class="ls-curve__none"[^>]*/>', curve)), 1)
        titles = re.findall(r"<title>(.*?)</title>", curve)
        self.assertIn(f"{self._time(self.FAILED)} · no value", titles)
        # three stretches of line: before the failure, after it, and after the
        # hour nothing was read — which breaks it with no mark of its own
        self.assertEqual(len(re.findall(r'<path class="ls-curve__line"', curve)), 3)

    def test_a_stretch_without_readings_is_a_plain_one(self):
        self._deploy()
        body = self._page()
        self.assertEqual(len(re.findall(r'class="ls-curve__none"',
                                        _curves(body)[0])), 1)
        self.assertIn("1 stretch without readings", body)
        self.assertIn("1 without a value", body)

    def test_every_kept_reading_is_on_its_history_page(self):
        self._deploy()
        response = self.client.get(f"/history{self.PATH}")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        rows = _reading_rows(body)
        self.assertEqual([row[0] for row in rows],
                         [self._time(minute)
                          for minute in sorted(self.MINUTES, reverse=True)])
        # beneath its status periods
        self.assertLess(body.index("<th>Since</th>"), body.index("ls-readings"))
        self.assertEqual(_curves(body), [])

    def test_the_setting_caps_the_rows(self):
        self._deploy()
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, reading_cap=3)):
            rows = _reading_rows(self._page())
        self.assertEqual(len(rows), 3)

    def test_the_checks_own_cap_wins(self):
        self._deploy(reading_cap=5)
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, reading_cap=3)):
            rows = _reading_rows(self._page())
        self.assertEqual(len(rows), 5)

    def test_a_cap_of_zero_leaves_the_curve_alone_and_every_reading_to_history(
            self):
        self._deploy(reading_cap=0)
        body = self._page()
        self.assertEqual(_reading_rows(body), [])
        self.assertEqual(len(_curves(body)), 1)
        self.assertIn(f'15 readings kept — every one is on the '
                      f'<a href="/history{self.PATH}">History page</a>', body)
        self.assertEqual(len(_reading_rows(
            self.client.get(f"/history{self.PATH}").get_data(as_text=True))),
            len(self.MINUTES))

    def test_the_page_says_how_many_it_shows_of_how_many_kept(self):
        self._deploy()
        body = self._page()
        self.assertIn("newest 10 of 15 readings", body)

    def test_a_measure_the_deployment_took_back_draws_no_curve(self):
        self._deploy(measures={"response_ms": None})
        body = self._page()
        self.assertEqual(_curves(body), [])
        self.assertEqual(len(_reading_rows(body)), 10)

    def test_a_node_that_stands_for_no_subject_shows_no_series(self):
        self._deploy()
        self.tree.upsert("/web/other", StatusCode.OK, frequency_seconds=180)
        body = self._page("/web/other")
        self.assertNotIn("ls-readings", body)
        self.assertEqual(_curves(body), [])

    def test_a_check_that_keeps_no_series_shows_none(self):
        self._deploy(series_keep=0)
        body = self._page()
        self.assertNotIn("ls-readings", body)
        self.assertEqual(_curves(body), [])

    def test_without_an_engine_there_is_no_series_to_show(self):
        self._deploy()
        app_module.engine = None
        body = self._page()
        self.assertNotIn("ls-readings", body)

    def test_a_polled_branch_page_carries_at_most_the_cap(self):
        # a node standing for a subject with children of its own renders the same
        # facts on its branch page, and the poll fragment renders them again
        from little_sister.engine import Engine
        from little_sister.series import MemoryStore, SeriesKey, SeriesRecord

        class _Host(Check):
            type_name = "probe-host"

            def measure(self):
                return ()

            def grade(self, measurements, now):
                return CheckResult(StatusCode.OK)

        check = _Host(path="/hosts/nas", subject="nas1", series_keep=40,
                      frequency_seconds=60, measures={"load": ""})
        store = MemoryStore()
        for minute in range(30):
            store.add(SeriesKey("probe-host", "/hosts/nas", "nas1"),
                      SeriesRecord({"load": minute / 10},
                                   self.T0 + timedelta(minutes=minute),
                                   code=StatusCode.OK, texts=("load fine",)),
                      keep=40)
        app_module.engine = Engine([check], self.tree, series=store)
        self.tree.upsert("/hosts/nas", StatusCode.OK, frequency_seconds=60,
                         subject="nas1", record={"load": 2.9})
        self.tree.upsert("/hosts/nas/disk", StatusCode.OK, frequency_seconds=60)
        for query in ("", "?fragment=1"):
            with self.subTest(query=query):
                body = self._page(f"/hosts/nas{query}")
                self.assertEqual(len(_reading_rows(body)), 10)
                self.assertEqual(len(_curves(body)), 1)
