import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
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

    # --- Reason overflow (#9): a dashboard card clamps its reasons to a *line
    # budget* (config.yaml reason_cap → the block's --reason-lines); the overflow
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
        # config.yaml's reason_cap is the line budget; it reaches both the full page
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
        # slice 3: the strip gets a watching-eye glyph, marking it as the monitor
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
        # slice 4: the density switch off (a form submit — the `view` marker — with
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
        # slice 8 (WCAG 1.1.1): a node box has no status word, so its cue is named for
        # assistive tech (role=img + aria-label); the card cue in the same view is not
        self._login()
        self.tree.upsert("/host/disk", StatusCode.ERROR, "disk full")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('role="img" aria-label="error"', body)   # the disk box cue speaks
        self.assertEqual(body.count('role="img"'), 1)          # only the box, not card

    def test_quiet_node_box_cue_not_announced(self):
        # slice 8 tweak: only a problem (warn/error) box announces; a quiet box keeps a
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
        # slice 10: the strip pill's whole-set popover surfaces every pin regardless of
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
        # slice 9: hide-idle now hides only never-reported (UNDEFINED); maintenance is
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
        # slice 10: the pill wears a live count of pinned nodes ("N in maintenance")
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
        # slice 10: the pill popover shows the first maintenance_cap pins, then a
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
        # slice 5: the density switch persists like depth — set on an explicit
        # change (SameSite=Lax), honoured on a later plain visit
        self._login()
        self.tree.upsert("/host/cpu", StatusCode.OK)   # quiet leaf, chip by default
        first = self.client.get("/status?view=1")        # chips unchecked
        self.assertIn("SameSite=Lax", first.headers.get("Set-Cookie", ""))
        body = self.client.get("/status").get_data(as_text=True)   # later plain visit
        self.assertNotIn("leaf-chip", body)              # density-off remembered
        self.assertIn("status-node s-ok", body)

    def test_hide_ok_persists_via_cookie(self):
        # slice 5: hide-ok persists across visits, like depth
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
