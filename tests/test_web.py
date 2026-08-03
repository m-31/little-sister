import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import __version__, icons, link_probe, links, secrets, watch_lines
from little_sister import app as app_module
from little_sister.checks import code
from little_sister.status import HEARTBEAT_PATH, StatusCode
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

    # --- Observation time on the dashboard and the detail page (ADR-0027): a card
    # states *when* beside *what*, but only where "when did the check behind this node
    # run?" has exactly one answer; the detail page never invents an instant. ---

    def test_card_shows_the_observation_time_before_the_status(self):
        # The `svc` container covers exactly one check, so its card inherits that
        # check's run time — rendered as a time of day in the configured timezone
        # (ADR-0006) and sitting directly before the cue + status word.
        self._login()
        self.tree.set_check_mount("/svc/api")
        self.tree.upsert("/svc/api", StatusCode.OK)
        stamp = self.tree.snapshot("/svc/api").timestamp
        shown = (datetime.fromisoformat(stamp).astimezone()
                 .astimezone(app_module.config.tzinfo).strftime("%H:%M:%S"))
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

    # --- Reason overflow (#9): a dashboard card clamps its reasons to a *line
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
        # the saved cookie is honoured on a later plain request
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

    def test_branches_script_ships_with_page_not_fragment(self):
        # like reasons.js / the popover assets: the behavior loads once with the page,
        # not on every ~10s poll fragment
        self._login()
        self._branchy_card()
        page = self.client.get("/status").get_data(as_text=True)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn("js/branches.js", page)
        self.assertNotIn("js/branches.js", frag)

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

    def test_node_box_cue_named_for_screen_readers(self):
        # WCAG 1.1.1: a node box has no status word, so its cue is named for
        # assistive tech (role=img + aria-label); the card cue in the same view is not
        self._login()
        self.tree.upsert("/host/disk", StatusCode.ERROR, "disk full")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('role="img" aria-label="error"', body)   # the disk box cue speaks
        self.assertEqual(body.count('role="img"'), 1)          # only the box, not card

    def test_quiet_node_box_cue_not_announced(self):
        # only a problem (warn/error) box announces; a quiet box keeps a
        # decorative aria-hidden cue, so a reader doesn't hear a stream of "ok"s
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
        # change (SameSite=Lax), honoured on a later plain visit
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
        # an untouched pin says nothing about a last change (ADR-0014 amendment)
        self.assertNotIn("Last changed by", body)

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
        # muted comes later in the stylesheet — stacking them renders gray, so
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
        # Bootstrap, so the band must not colour this line itself
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
        # btn-info was the one colour on the detail page that followed no theme
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
        # A reader mid-incident reads a colour before a sentence, and this is the
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
        # outline secondary is one grey on every canvas, 3.76:1 on the dark one
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
        # says (ADR-0030, amended): without this, somebody pressing *check now* and
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
        # colour up here would compete with it. The sentence sits *inside* the
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
