import os
import unittest
from unittest import TestCase, mock

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import __version__, secrets
from little_sister import app as app_module
from little_sister.checks import code
from little_sister.status import StatusCode
from little_sister.tree import StatusTree


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

    def test_config_shown_on_detail_page(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK,
                         config="- **url:** http://example")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("Configuration", body)
        self.assertIn("http://example", body)

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

    def test_reason_raw_html_is_escaped_in_page(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.ERROR, "<script>x</script>")
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertNotIn("<script>x</script>", body)
        self.assertIn("&lt;script&gt;", body)

    # --- Reason overflow (#9): a dashboard card caps how many reason entries it
    # shows and clamps a tall block's height, with an in-place "show all (N)".
    # Trim is by entry (a marked class) + CSS only — every entry stays in the DOM,
    # never cut mid-HTML. The leaf detail page and the JSON envelope stay full. ---

    def test_reason_cap_marks_entries_and_offers_show_all(self):
        self._login()
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [f"workflow {i} failed" for i in range(1, 9)])  # 8 > cap 6
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-reason-total="8"', body)      # the block knows the total
        self.assertEqual(body.count("reason-extra"), 2)   # only entries 7 and 8
        self.assertIn("show all (8)", body)               # the in-place affordance
        self.assertIn("workflow 8 failed", body)          # nothing omitted from the DOM

    def test_reason_cap_absent_at_the_boundary(self):
        # exactly the cap (6) renders whole — no marked extras, no toggle
        self._login()
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [f"workflow {i} failed" for i in range(1, 7)])  # 6 == cap
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-reason-total="6"', body)
        self.assertNotIn("reason-extra", body)
        self.assertNotIn("show all", body)

    def test_reason_cap_absent_on_detail_page(self):
        # the leaf detail page keeps everything, uncapped (check.html, not the grid)
        self._login()
        self.tree.upsert("/svc/api", StatusCode.ERROR,
                         [f"line {i}" for i in range(1, 11)])   # 10 > cap
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("line 1", body)
        self.assertIn("line 10", body)                    # the tail is present
        self.assertNotIn("reason-block", body)            # no cap machinery
        self.assertNotIn("reason-extra", body)
        self.assertNotIn("show all", body)

    def test_reason_cap_fragment_is_well_formed(self):
        # trim by entry + CSS only: the polled fragment never cuts rendered HTML
        # mid-tag, even with a tall code() block among many linked reasons
        self._login()
        trace = code("\n".join(f"frame {i}" for i in range(1, 60)))
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [trace] + [f"[run {i}](https://ci.example/{i}) failed"
                                    for i in range(1, 10)])   # 10 reasons total
        body = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertEqual(body.count("<pre>"), body.count("</pre>"))  # code fence closed
        self.assertEqual(body.count("<a "), body.count("</a>"))      # every link closed
        self.assertIn('data-reason-total="10"', body)
        self.assertIn("show all (10)", body)

    def test_reasons_script_ships_with_page_not_fragment(self):
        # like the popover assets: the behaviour loads once with the page, not on
        # every ~10s poll fragment
        self._login()
        self.tree.upsert("/db", StatusCode.ERROR, "down")
        page = self.client.get("/status").get_data(as_text=True)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("js/reasons.js", page)
        self.assertNotIn("js/reasons.js", frag)

    # --- Dashboard layout (#24): the engine self-heartbeat moves out of the card
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

    def test_no_strip_without_a_heartbeat_node(self):
        # a branch page (or a tree with no heartbeat) shows no strip
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("ls-strip", body)

    def test_heartbeat_title_reaches_strip_and_popover_map(self):
        # The strip is a node like any other (#24): a nodes.yaml title/about on
        # the heartbeat shows in the strip and feeds the hover-card map.
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.set_title("/little-sister", "engine heartbeat")
        self.tree.set_about("/little-sister", "the pulse of the scheduler")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("engine heartbeat", body)             # title, in the strip
        self.assertIn("the pulse of the scheduler", body)   # about: only the map

    def test_heartbeat_with_children_stays_a_card(self):
        # Belt and braces: the strip is a one-line bar, so a heartbeat that
        # (somehow) grew children is not lifted — better a card in the grid
        # than a subtree hidden behind the strip. The loader keeps custom
        # checks off the reserved line in the first place.
        self._login()
        self.tree.upsert("/little-sister", StatusCode.OK, frequency_seconds=3600)
        self.tree.upsert("/little-sister/satellite", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("ls-strip", body)
        self.assertIn('status-card__head" data-path="/little-sister"', body)
        self.assertIn("satellite", body)                    # nothing vanishes

    def test_quiet_leaf_renders_as_a_chip(self):
        # a card's OK leaf collapses to a compact chip (name + colour); its reason,
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
        # the saved cookie is honoured on a later plain request
        self.assertNotIn(
            "boom", self.client.get("/status").get_data(as_text=True))

    def test_depth_zero_shows_single_overall_card(self):
        self._login()
        self.tree.upsert("/sys/host/check", StatusCode.ERROR, "down")
        body = self.client.get("/status?depth=0").get_data(as_text=True)
        # depth 0 collapses the whole tree to one rolled-up "overall" card
        self.assertIn("overall", body)
        # it shows the rolled-up colour and stays bold (it carries the status)
        self.assertIn('status-card s-error"', body)
        # nothing below the root is rendered
        self.assertNotIn("status-node s-", body)
        self.assertNotIn("down", body)

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
        self.assertIn("Set by", body)
        self.assertIn("pan", body)          # set_by = the session user
        self.assertIn("Expires", body)

    def test_maintenance_blocks_non_admin(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        response = self.client.post("/maintenance",
                                    data={"path": "db", "action": "set"})
        self.assertEqual(response.status_code, 403)

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
        # muted comes later in the stylesheet — stacking them renders grey, so
        # the failure path must remove muted for the red to actually show
        js = self.client.get("/static/js/poll.js").get_data(as_text=True)
        self.assertIn("classList.remove('text-muted')", js)
        self.assertIn("classList.add('text-danger')", js)

    def test_poll_js_escalates_a_sustained_outage(self):
        # ADR-0005 update note: six consecutive misses escalate to a banner,
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
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("Engine not started", body)

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
        self.assertIn("· in 100s", body)
        self.assertIn("15:50:57", body)            # last run start, check a
        self.assertIn("· 412 ms", body)
        self.assertIn("15:51:00", body)            # running since, check b
        self.assertIn("· 3.4 s", body)
        self.assertIn("—", body)                   # check b has no last run yet
        self.assertNotIn(">running<", body)        # the old placeholder is gone

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
        # "updated …" honours config.time_format rather than toLocaleTimeString
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


class SettingResolutionTests(TestCase):
    """SECRET_KEY / LITTLE_SISTER_API_TOKENS at startup (ADR-0023 update)."""

    def setUp(self):
        for patcher in (mock.patch.dict(os.environ),
                        mock.patch.dict(secrets._resolvers)):
            patcher.start()
            self.addCleanup(patcher.stop)

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
        key = app_module._session_key()
        self.assertEqual(len(key), 64)

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


if __name__ == "__main__":
    unittest.main()
