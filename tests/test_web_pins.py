"""Branch pins in the UI (ADR-0014): the card pin control and the subtree
page's maintenance card. The model, POST /maintenance, persistence and the
reaper always accepted a container pin — these tests pin the surfaces down."""

import os
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.app import (
    _maintenance_pins,
    _maintenance_rows,
    _MaintenancePin,
)
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

# The shared maintenance card's heading — distinguishes the card from the pin
# dialog, whose title reads "Maintenance — <name>".
CARD_HEADING = 'text-uppercase">Maintenance<'


class BranchPinTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _viewer(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    # ----- the card pin control -----

    def test_admin_card_head_carries_pin_control(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="pin-control"', body)
        self.assertIn('data-pin-path="/system"', body)
        self.assertIn('data-pin-kids="1"', body)           # a branch card
        self.assertIn('aria-haspopup="dialog"', body)
        # the no-JS fallback is the node's own page
        self.assertIn('href="/status/system"\n   role="button"', body)
        self.assertIn("Which formats can I use?", body)

    def test_viewer_sees_no_pin_control_or_dialog(self):
        self._viewer()
        self.tree.upsert("/system/alpha", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("pin-control", body)
        self.assertNotIn("pin-card", body)
        self.assertNotIn("js/pin.js", body)

    def test_kiosk_hides_pin_control_and_dialog_even_for_admin(self):
        # the kiosk is the wall display: no chrome to click (ADR-0029)
        self._login()
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.tree.upsert("/system/alpha", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("pin-control", body)
        self.assertNotIn("pin-card", body)

    def test_control_rides_the_fragment_dialog_ships_with_the_page(self):
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        page = self.client.get("/status").get_data(as_text=True)
        self.assertIn("pin-control", frag)
        self.assertNotIn('id="pin-card"', frag)
        self.assertNotIn("js/pin.js", frag)
        self.assertIn('id="pin-card"', page)
        self.assertIn("js/pin.js", page)

    def test_leaf_card_control_has_no_kids_marker(self):
        self._login()
        self.tree.upsert("/uplink", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-pin-path="/uplink"', body)
        self.assertNotIn("data-pin-kids", body)

    def test_pinned_card_control_carries_pin_state(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self.tree.set_maintenance(
            "/db", "planned", expires_at=datetime.now() + timedelta(hours=2),
            set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-pin-pinned="1"', body)
        self.assertIn("data-pin-expires=", body)

    # ----- the subtree page's maintenance card -----

    def test_branch_page_shows_the_maintenance_card(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn(CARD_HEADING, body)
        self.assertIn("Silences <strong>/system/alpha</strong>", body)
        self.assertIn("nothing under here will alarm", body)
        self.assertIn("default 7d", body)                  # the deployment default

    def test_branch_page_shows_the_current_pin(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self.tree.set_maintenance(
            "/system/alpha", "rebuild",
            expires_at=datetime.now() + timedelta(days=1), set_by="pan")
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn("This node is in maintenance.", body)
        self.assertIn("Clear maintenance", body)

    def test_overview_root_gets_no_maintenance_card(self):
        # a silence-everything form on the overview is a foot-gun; the root
        # stays curl-only
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('id="pin-card"', body)               # the dialog ships
        self.assertNotIn(CARD_HEADING, body)               # the card does not

    def test_viewer_branch_page_has_no_maintenance_card(self):
        self._viewer()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertNotIn(CARD_HEADING, body)

    def test_missing_branch_page_survives_the_admin_card(self):
        self._login()
        body = self.client.get("/status/nope").get_data(as_text=True)
        self.assertIn("No such branch", body)
        self.assertNotIn(CARD_HEADING, body)

    def test_kiosk_branch_page_has_no_maintenance_card(self):
        self._login()
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertNotIn(CARD_HEADING, body)

    def test_leaf_detail_page_keeps_its_form(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn(CARD_HEADING, body)
        self.assertIn("Set maintenance", body)
        self.assertIn("Silences <strong>/svc/api</strong>", body)
        self.assertIn("The check keeps running", body)     # the leaf sentence
        self.assertIn("default 7d", body)
        self.assertIn("Duration or expiry", body)
        self.assertIn("Which formats can I use?", body)
        self.assertIn("Timezone: Europe/Berlin", body)
        self.assertIn("used when the input has no", body)
        self.assertIn("Next 10 July, at midnight", body)
        self.assertIn("Next Friday at 12:00", body)

    def test_open_editor_replaces_its_trigger_only_when_cancel_is_enhanced(self):
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        selector = (
            ".maintenance-edit-enhanced "
            ".maintenance-editor-disclosure[open] > summary")
        rule = css.split(selector, 1)[1].split("}", 1)[0]
        self.assertIn("display: none", rule)
        script = self.client.get(
            "/static/js/maintenance-edit.js").get_data(as_text=True)
        self.assertIn(
            'classList.add("maintenance-edit-enhanced")', script)

    def test_duration_placeholder_follows_the_configured_default(self):
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, maintenance_default_expiry="36h")):
            body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertIn("default 36h", body)
        self.assertNotIn("default 7d", body)

    # ----- pinning a container end to end -----

    def test_post_pins_a_container_and_children_keep_their_colors(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self.tree.upsert("/system/alpha/cpu", StatusCode.ERROR, "hot")
        response = self.client.post("/maintenance", data={
            "path": "system/alpha", "action": "set", "reason": "rebuild"})
        self.assertEqual(response.status_code, 302)
        # default redirect: the node's own page (the leaf form's behavior)
        self.assertTrue(
            response.headers["Location"].endswith("/status/system/alpha"))
        self.assertEqual(self.tree.effective("/system/alpha"),
                         StatusCode.MAINTENANCE)
        snap = self.tree.snapshot("/system/alpha")
        self.assertTrue(snap.maintenance)                  # one pin, at the node
        kids = {child.name: child.code for child in snap.children}
        self.assertEqual(kids["cpu"], StatusCode.ERROR)    # children keep colors
        self.assertEqual(kids["disk"], StatusCode.OK)

    def test_post_returns_to_next_when_given(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        response = self.client.post("/maintenance", data={
            "path": "db", "action": "set", "reason": "planned",
            "next": "/status?depth=2"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/status?depth=2"))

    def test_post_rejects_unsafe_next(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        for evil in ("//evil.example", "/\\evil.example", "https://evil.example"):
            with self.subTest(next=evil):
                response = self.client.post("/maintenance", data={
                    "path": "db", "action": "clear", "next": evil})
                self.assertTrue(
                    response.headers["Location"].endswith("/status"))


class EditAndConflictTests(TestCase):
    """Editing a pin without clearing it first, and the conflict page a refused
    compare-and-set lands on (ADR-0014)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self, user="pan", password="12345678"):
        self.client.post("/login", data={"username": user, "password": password})

    def _pin(self, path="/db", reason="ada wrote this", by="ada"):
        return self.tree.set_maintenance(
            path, reason, expires_at=datetime.now() + timedelta(days=1),
            set_by=by).current

    # ----- the set form is reachable, and prefilled, while pinned -----

    def test_pinned_branch_page_offers_the_prefilled_set_form(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self._pin("/system/alpha", "rebuild")
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn("Save changes", body)                 # not only "Clear"
        self.assertIn("Clear maintenance", body)
        self.assertIn('id="node-maintenance-reason" name="reason"', body)
        self.assertIn('placeholder="why?">rebuild</textarea>', body)
        # expiry is deliberately NOT prefilled: blank is the configured default
        # here exactly as it is on an unpinned node
        self.assertIn('id="node-maintenance-duration" name="duration" value=""', body)
        self.assertIn('placeholder="e.g. 2h or Friday — default 7d"', body)

    def test_pinned_node_is_rendered_first_and_keeps_raw_markdown_to_edit(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self._pin(
            "/system/alpha",
            "**Rebuild** — [runbook](https://ops.example/runbook)\n\n<script>x</script>",
        )

        body = self.client.get("/status/system/alpha").get_data(as_text=True)

        self.assertIn("<strong>Rebuild</strong>", body)
        self.assertIn('href="https://ops.example/runbook"', body)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", body)
        self.assertNotIn("<script>x</script>", body)
        self.assertIn(">Edit maintenance</summary>", body)
        self.assertIn("**Rebuild** — [runbook]", body)  # raw textarea source


    def test_both_forms_carry_the_token(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        entry = self._pin("/system/alpha")
        assert entry is not None
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertEqual(
            body.count(f'name="set_at" value="{entry.set_at}"'), 2)

    def test_unpinned_form_claims_nothing_is_pinned(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn('name="set_at" value=""', body)

    def test_pinned_card_control_carries_reason_and_token(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned")
        assert entry is not None
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-pin-reason="planned"', body)
        self.assertIn(f'data-pin-token="{entry.set_at}"', body)
        self.assertIn('data-pin-by="ada"', body)

    def test_pinned_card_carries_server_rendered_read_source(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "See **runbook**")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('class="pin-control__reason-source"', body)
        self.assertIn("<strong>runbook</strong>", body)
        self.assertIn('id="pin-card-read"', body)
        self.assertIn('id="pin-card-edit"', body)

    def test_editing_keeps_the_reason_and_the_original_author(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned kernel upgrade")
        assert entry is not None
        response = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "planned kernel upgrade",
            "duration": "3d", "set_at": entry.set_at})
        self.assertEqual(response.status_code, 302)         # no conflict
        after = self.tree.maintenance_entry("/db")
        assert after is not None
        self.assertEqual(after.reason, "planned kernel upgrade")
        self.assertEqual(after.created_by, "ada")           # who pinned it
        self.assertEqual(after.set_by, "pan")               # who edited it
        # the node never left maintenance on the way through
        self.assertEqual(self.tree.effective("/db"), StatusCode.MAINTENANCE)

    def test_node_page_names_both_authors_after_an_edit(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned")
        assert entry is not None
        self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "planned, longer",
            "duration": "3d", "set_at": entry.set_at})
        body = self.client.get("/status/db").get_data(as_text=True)
        self.assertIn("Pinned by <strong>ada</strong>", body)
        self.assertIn("Last changed by <strong>pan</strong>", body)

    # ----- the lost update -----

    def test_a_stale_token_writes_nothing_and_shows_both_texts(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        self._pin("/db", "ben wrote this", by="ben")           # ben got there first
        response = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "pan wrote this",
            "duration": "2h", "set_at": stale.set_at, "next": "/status?depth=2"})
        self.assertEqual(response.status_code, 200)         # not a redirect
        body = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", body)
        self.assertIn("ben wrote this", body)                  # the stored text
        self.assertIn('placeholder="why?">pan wrote this</textarea>', body)
        self.assertIn("ben", body)                          # who beat me to it
        self.assertIn("/status?depth=2", body)              # where I came from
        # and the stored pin is untouched
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.reason, "ben wrote this")

    def test_the_conflict_form_carries_the_refreshed_token(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        fresh = self._pin("/db", "ben wrote this", by="ben")
        assert fresh is not None
        body = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "mine",
            "set_at": stale.set_at}).get_data(as_text=True)
        self.assertIn(f'name="set_at" value="{fresh.set_at}"', body)
        self.assertNotIn(f'name="set_at" value="{stale.set_at}"', body)

    def test_taking_the_stored_reason_is_one_click(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        self._pin("/db", "ben wrote this", by="ben")
        body = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "mine", "duration": "2h",
            "set_at": stale.set_at}).get_data(as_text=True)
        self.assertIn("Keep the stored reason", body)
        self.assertIn('name="reason" value="ben wrote this"', body)
        self.assertIn('name="duration" value="2h"', body)   # my window kept

    def test_clearing_someone_elses_pin_is_refused_too(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        self._pin("/db", "ben wrote this", by="ben")
        response = self.client.post("/maintenance", data={
            "path": "/db", "action": "clear", "set_at": stale.set_at})
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Clear this pin", body)
        self.assertIn("ben wrote this", body)
        self.assertEqual(self.tree.effective("/db"), StatusCode.MAINTENANCE)

    def test_a_pin_that_vanished_says_so(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        self.tree.clear_maintenance("/db")                  # expired, or cleared
        body = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "mine",
            "set_at": stale.set_at}).get_data(as_text=True)
        self.assertIn("gone — someone cleared it", body)
        self.assertIn('name="set_at" value=""', body)       # re-pin from nothing
        self.assertIn('placeholder="why?">mine</textarea>', body)  # my words survive

    def test_a_post_without_a_token_still_writes(self):
        # a hand-rolled client, never one of our forms: today's behavior
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "ada wrote this")
        response = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "scripted"})
        self.assertEqual(response.status_code, 302)
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.reason, "scripted")

    def test_conflict_page_needs_admin(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        response = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "set_at": "whatever"})
        self.assertEqual(response.status_code, 403)

    # ----- who set it, wherever the pin is -----

    def test_maintenance_page_names_both_authors(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned")
        assert entry is not None
        self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "planned, longer",
            "set_at": entry.set_at})
        body = self.client.get("/maintenance").get_data(as_text=True)
        self.assertIn("pinned by <strong>ada</strong>", body)
        self.assertIn("last changed by", body)
        self.assertIn("<strong>pan</strong>", body)

    def test_maintenance_page_renders_the_explanation_as_markdown(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "See **owner** and [runbook](https://ops.example/runbook)")
        body = self.client.get("/maintenance").get_data(as_text=True)
        self.assertIn("<strong>owner</strong>", body)
        self.assertIn('href="https://ops.example/runbook"', body)

    def test_maintenance_page_says_nothing_extra_about_an_untouched_pin(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "planned")
        body = self.client.get("/maintenance").get_data(as_text=True)
        self.assertIn("pinned by <strong>ada</strong>", body)
        self.assertNotIn("last changed by", body)

    def test_popover_names_the_last_writer(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "planned", by="ada")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('<span class="maintenance-pop__by">ada</span>', body)

    def test_a_reason_with_quotes_survives_the_round_trip(self):
        # The stored text is rendered and mine goes back into a textarea; autoescape
        # owns both untrusted halves, so a quote cannot end either context.
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "plain")
        assert stale is not None
        self._pin("/db", 'ben\'s "big" upgrade', by="ben")
        body = self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "pan's turn",
            "set_at": stale.set_at}).get_data(as_text=True)
        self.assertIn("ben&#39;s &#34;big&#34; upgrade", body)      # the stored text
        self.assertIn('placeholder="why?">pan&#39;s turn</textarea>', body)  # and mine


class EntryPinSurfaceTests(TestCase):
    """The leaf detail page's per-line control, and quiet made visible (ADR-0036)."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _viewer(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _findings(self):
        self.tree.upsert("/wiz", StatusCode.ERROR,
                         {"acme/pr-412": "waiting on review",
                          "acme/pr-77": "stale branch"})

    def _prose(self):
        self.tree.upsert("/db", StatusCode.ERROR,
                         ["check error: unreachable", "Traceback…"])

    def _page(self, path="/status/wiz"):
        return self.client.get(path).get_data(as_text=True)

    # ----- the control -----

    def test_an_admin_gets_a_pin_control_on_every_member_line(self):
        self._login()
        self._findings()
        body = self._page()
        self.assertEqual(body.count('class="reason-pin"'), 2)
        self.assertIn('name="slug" value="acme/pr-412"', body)
        self.assertIn("Set maintenance", body)
        self.assertIn("reason-pin__toggle", body)

    def test_the_pin_summary_does_not_add_an_inline_line_box_to_the_rail(self):
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        rule = css.split(".reason-pin > summary {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex", rule)

    def test_prose_gets_no_per_line_control(self):
        # its unit of suppression is the node pin; a per-line button there would
        # offer to silence half of one condition
        self._login()
        self._prose()
        body = self._page("/status/db")
        self.assertNotIn('class="reason-pin"', body)
        self.assertIn("Traceback", body)

    def test_a_viewer_gets_no_control(self):
        self._viewer()
        self._findings()
        self.assertNotIn('class="reason-pin"', self._page())

    def test_the_control_claims_nothing_is_pinned(self):
        self._login()
        self._findings()
        self.assertIn('name="set_at" value=""', self._page())

    # ----- pinning through the form -----

    def test_pinning_one_line_leaves_the_others_alarming(self):
        self._login()
        self._findings()
        response = self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "reason": "ada is on it", "duration": "2d"})
        self.assertEqual(response.status_code, 302)
        snap = self.tree.snapshot("/wiz")
        self.assertEqual(snap.own_code, StatusCode.ERROR)
        self.assertEqual(snap.quiet_reasons, 1)
        body = self._page()
        self.assertIn("is-quiet", body)
        self.assertIn("ada is on it", body)
        self.assertIn("1 of 2 in maintenance", body)
        self.assertIn("Clear maintenance", body)

    def test_a_pinned_line_can_be_edited_in_place_with_raw_markdown(self):
        self._login()
        self._findings()
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "reason": "**Ada** has [ticket](https://issues.example/412)",
            "duration": "2d", "set_at": ""})
        entry = self.tree.entry_maintenance("/wiz", "acme/pr-412")
        assert entry is not None

        body = self._page()

        self.assertIn("<strong>Ada</strong>", body)
        self.assertIn('href="https://issues.example/412"', body)
        self.assertIn(">Edit maintenance</summary>", body)
        self.assertIn(f'name="set_at" value="{entry.set_at}"', body)
        self.assertIn("**Ada** has [ticket]", body)  # untouched textarea source
        self.assertIn("Save changes", body)
        self.assertIn("Clear maintenance", body)

    def test_silencing_every_line_says_nothing_is_reporting(self):
        self._login()
        self._findings()
        for slug in ("acme/pr-412", "acme/pr-77"):
            self.client.post("/maintenance", data={
                "path": "/wiz", "slug": slug, "action": "set", "duration": "2d"})
        self.assertEqual(self.tree.snapshot("/wiz").own_code,
                         StatusCode.MAINTENANCE)
        self.assertIn("nothing here is reporting", self._page())

    def test_unsilencing_a_line(self):
        self._login()
        self._findings()
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-77", "action": "set",
            "duration": "2d"})
        entry = self.tree.entry_maintenance("/wiz", "acme/pr-77")
        assert entry is not None
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-77", "action": "clear",
            "set_at": entry.set_at})
        self.assertIsNone(self.tree.entry_maintenance("/wiz", "acme/pr-77"))
        self.assertEqual(self.tree.snapshot("/wiz").quiet_reasons, 0)

    def test_a_slug_with_a_slash_survives_the_round_trip(self):
        # the natural slug for a discovered entry has one, which is why addressing
        # is a form field / query parameter and never a path segment
        self._login()
        self._findings()
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "duration": "2d"})
        self.assertIsNotNone(self.tree.entry_maintenance("/wiz", "acme/pr-412"))

    def test_an_entry_pin_is_guarded_like_a_node_pin(self):
        self._login()
        self._findings()
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "reason": "ada is on it", "duration": "2d"})
        response = self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "reason": "mine", "set_at": ""})     # I believed nothing was pinned
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", body)
        self.assertIn("ada is on it", body)
        self.assertIn('name="slug" value="acme/pr-412"', body)
        entry = self.tree.entry_maintenance("/wiz", "acme/pr-412")
        assert entry is not None
        self.assertEqual(entry.reason, "ada is on it")

    def test_a_non_admin_cannot_pin_a_line(self):
        self._viewer()
        self._findings()
        response = self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set"})
        self.assertEqual(response.status_code, 403)

    # ----- the dashboard -----

    def test_the_card_shows_the_quiet_count(self):
        self._login()
        self.tree.upsert("/site/wiz", StatusCode.ERROR,
                         {"a": "one", "b": "two"})
        self.client.post("/maintenance", data={
            "path": "/site/wiz", "slug": "a", "action": "set", "duration": "2d"})
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("1 of 2 in maintenance", body)
        self.assertIn("status-node__reason md-body is-quiet", body)


class EntryPinIndexTests(TestCase):
    """An entry pin in the **maintenance surfaces** (ADR-0036, ADR-0032 rule 5).

    A silenced reason used to be visible only on its own node's page: the index
    walked ``maintenance_entry`` and knew nothing of ``ReasonLine.maintenance``, so
    an entry pin reached neither the strip pill, nor the "contains maintenance" pip,
    nor ``/maintenance``. An admin asking *what is silenced right now?* got a quietly
    incomplete answer — and, in the sharp case, a node whose members are **all**
    pinned reads ``MAINTENANCE`` on the dashboard while the maintenance page denied
    any pin existed there. A blue card no index claims is what rule 5 forbids.

    The two surfaces answer different questions and so have different shapes: the
    capped popover summarizes **one row per node**, ``/maintenance`` lists **one row
    per pin**. Both are pinned down here.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _findings(self, path="/site/wiz"):
        """A members node: two findings, in the check's order."""
        self.tree.upsert(path, StatusCode.ERROR,
                         {"acme/pr-412": "waiting on review",
                          "acme/pr-77": "stale branch"})

    def _pin_line(self, path, slug, reason="ada is on it"):
        return self.client.post("/maintenance", data={
            "path": path, "slug": slug, "action": "set",
            "reason": reason, "duration": "2d"})

    def _pin_node(self, path, reason="whole box", duration="3d"):
        return self.client.post("/maintenance", data={
            "path": path, "action": "set", "reason": reason, "duration": duration})

    def _page(self):
        return self.client.get("/maintenance").get_data(as_text=True)

    def _dashboard(self):
        return self.client.get("/status").get_data(as_text=True)

    # ----- /maintenance: one row per pin, and two texts in two columns -----

    def test_an_entry_pin_reaches_the_maintenance_page(self):
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        body = self._page()
        self.assertNotIn("No nodes are in maintenance", body)
        self.assertIn("/site/wiz", body)
        self.assertIn("waiting on review", body)        # what is silenced
        self.assertIn("ada is on it", body)             # why it is

    def test_the_two_texts_are_not_under_one_heading(self):
        # `ReasonLine.text` and `MaintenanceEntry.reason` are both called "reason"
        # in the model and are not the same kind of thing.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        body = self._page()
        self.assertIn("<th>Silenced</th>", body)
        self.assertIn("<th>Why</th>", body)
        self.assertNotIn("<th>Reason</th>", body)

    def test_a_node_pin_says_it_covers_the_whole_node(self):
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self._pin_node("/db")
        self.assertIn("the whole node", self._page())

    def test_the_slug_is_never_rendered_as_text(self):
        # ADR-0036 makes it opaque; it may travel in a link and nowhere else.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        without_links = re.sub(r'href="[^"]*"', "", self._page())
        self.assertNotIn("acme/pr-412", without_links)

    def test_entry_pins_keep_the_checks_order_not_the_pinning_order(self):
        # The order a check emits its entries in is information (severity, API
        # order); an opaque slug sorted alphabetically would scramble it.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-77")
        self._pin_line("/site/wiz", "acme/pr-412")     # pinned second, listed first
        body = self._page()
        self.assertLess(body.index("waiting on review"), body.index("stale branch"))

    # ----- the popover: one row per node, never one per line -----

    def test_an_entry_pinned_node_is_one_row_carrying_a_count(self):
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        body = self._dashboard()
        self.assertIn("maintenance-pill", body)
        self.assertIn('maintenance-pill__count">1<', body)
        self.assertIn("1 of 2 reasons", body)

    def test_many_pinned_findings_do_not_evict_the_other_nodes(self):
        # the reason the popover summarizes: it is capped, and twenty rows from one
        # node would push every other node out of it.
        self.tree.upsert("/site/wiz", StatusCode.ERROR,
                         {f"f-{i}": f"finding {i}" for i in range(20)})
        self.tree.upsert("/site/db", StatusCode.ERROR, "boom")
        for i in range(3):
            self._pin_line("/site/wiz", f"f-{i}")
        self._pin_node("/site/db")
        body = self._dashboard()
        self.assertIn('maintenance-pill__count">2<', body)
        self.assertIn("3 of 20 reasons", body)

    def test_all_members_pinned_reads_all_rather_than_n_of_n(self):
        # THE reported case: the card is blue with no node pin on it, and this row
        # is the only thing that explains why.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        self._pin_line("/site/wiz", "acme/pr-77")
        self.assertEqual(self.tree.snapshot("/site/wiz").own_code,
                         StatusCode.MAINTENANCE)
        body = self._dashboard()
        self.assertIn("all 2 reasons", body)
        self.assertNotIn("2 of 2 reasons", body)
        # and the page that denied it now lists both
        page = self._page()
        self.assertIn("waiting on review", page)
        self.assertIn("stale branch", page)

    def test_a_node_pin_that_also_holds_entry_pins_is_one_row(self):
        """**Promoted from a unit test**, which is the point of the promotion.

        This shape was unreachable through the tree while a node pin overwrote the
        node's reading: its members vanished from the snapshot and there was nothing
        left to count, so the case could only be built by hand from two
        ``_MaintenancePin`` values. The keystone keeps the reading, so the state now
        arrives on its own — pin a line, pin the node, read the dashboard.
        """
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412", reason="ada is on it")
        self._pin_node("/site/wiz", reason="whole box")
        body = self._dashboard()
        self.assertIn('maintenance-pill__count">1<', body)   # one row, not two
        self.assertIn("+ 1 reason", body)                    # the count as a suffix
        self.assertNotIn("1 of 2 reasons", body)
        self.assertIn("whole box", body)          # the node pin's note leads
        self.assertNotIn("ada is on it", body)    # not the line's
        # and `/maintenance` still lists both, the node's own pin first
        page = self._page()
        self.assertLess(page.index("the whole node"), page.index("waiting on review"))
        self.assertIn("ada is on it", page)

    def test_the_view_types_still_order_a_nodes_pins_by_hand(self):
        # the unit-level half kept: `slot` is what puts a node's own pin ahead of
        # its entries, and it is easier to state here than to arrange in a tree.
        node_pin = _MaintenancePin(path="/site/wiz", title="", note="whole box",
                                   remaining="3d", total=2,
                                   expires_at="2026-08-05T00:00:00")
        entry_pin = _MaintenancePin(path="/site/wiz", title="", note="ada is on it",
                                    remaining="2d", slug="acme/pr-412",
                                    line="waiting on review", slot=0, total=2,
                                    expires_at="2026-08-04T00:00:00")
        rows = _maintenance_rows([node_pin], [entry_pin])
        self.assertEqual((len(rows), rows[0].pinned, rows[0].quiet), (1, True, 1))
        self.assertEqual((rows[0].note, rows[0].remaining), ("whole box", "3d"))
        pins = _maintenance_pins([node_pin], [entry_pin])
        self.assertEqual([pin.slug for pin in pins], ["", "acme/pr-412"])

    def test_several_entry_pins_name_no_single_justification(self):
        # one of three notes shown as if it were the row's is worse than none;
        # `/maintenance` carries them all.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412", reason="ada is on it")
        self._pin_line("/site/wiz", "acme/pr-77", reason="ben is on it")
        body = self._dashboard()
        self.assertNotIn("ada is on it", body)
        self.assertNotIn("ben is on it", body)
        self.assertIn("ada is on it", self._page())
        self.assertIn("ben is on it", self._page())

    # ----- the "contains maintenance" pip -----

    def test_a_card_over_an_entry_pinned_node_gets_the_pip(self):
        # the case that makes this more than bookkeeping: in dense mode a node whose
        # members are all pinned reads MAINTENANCE, so it collapses to a leaf chip,
        # and a chip draws neither reasons nor a quiet count.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        body = self._dashboard()
        self.assertIn("maintenance-pip", body)
        self.assertIn('data-pop-for="/site"', body)

    def test_an_entry_pinned_card_needs_no_pip_of_its_own(self):
        # its card already draws the quiet count. (`/wiz` is a root, so it *is* a
        # card here — the pip is only ever drawn on one.)
        self._findings("/wiz")
        self._pin_line("/wiz", "acme/pr-412")
        body = self._dashboard()
        self.assertIn("maintenance-pill", body)                 # the pin is indexed
        self.assertNotIn('data-pop-for="/wiz"', body)           # but no pip here

    def test_an_entry_pin_does_not_hide_a_pinned_descendant(self):
        # An entry pin cancels nothing below it — it silences one of this node's own
        # lines and leaves every child reporting — so unlike a node pin it must not
        # take this node out of the ancestor set.
        self._findings("/wiz")
        self.tree.upsert("/wiz/sub", StatusCode.ERROR, "child boom")
        self._pin_line("/wiz", "acme/pr-412")
        self._pin_node("/wiz/sub")
        self.assertIn('data-pop-for="/wiz"', self._dashboard())

    def test_a_node_pin_still_takes_its_own_card_out(self):
        # the other half of the same rule, unchanged: a node pin cancels its whole
        # subtree, so a pip below it would point at something already covered.
        self.tree.upsert("/wiz", StatusCode.ERROR, "boom")
        self.tree.upsert("/wiz/sub", StatusCode.ERROR, "child boom")
        self._pin_node("/wiz")
        self._pin_node("/wiz/sub")
        self.assertNotIn('data-pop-for="/wiz"', self._dashboard())

    # ----- the deep link, and the pin whose line went away -----

    def test_the_index_links_to_the_line_and_the_page_marks_it(self):
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        href = re.search(r'href="(/status/site/wiz[^"]*)"', self._page()).group(1)
        self.assertTrue(href.endswith("#pinned-reason"), href)
        page = self.client.get(href.split("#")[0]).get_data(as_text=True)
        self.assertIn('id="pinned-reason"', page)
        self.assertIn("is-focused", page)
        # and it marks the line it was asked for, not the first one
        marked_and_after = page.split('id="pinned-reason"', 1)[1]
        self.assertLess(marked_and_after.index("waiting on review"),
                        marked_and_after.index("stale branch"))

    def test_an_unasked_page_marks_nothing(self):
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        page = self.client.get("/status/site/wiz").get_data(as_text=True)
        self.assertNotIn('id="pinned-reason"', page)

    def test_a_pin_whose_line_stopped_being_reported_says_so(self):
        # suspended, not deleted (ADR-0036 decision 6). This is the one surface that
        # can say it; an anchor could only have failed to scroll.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        self.tree.upsert("/site/wiz", StatusCode.ERROR,
                         {"acme/pr-77": "stale branch"})
        self.assertIsNotNone(self.tree.entry_maintenance("/site/wiz", "acme/pr-412"))
        page = self.client.get(
            "/status/site/wiz?reason=acme/pr-412").get_data(as_text=True)
        self.assertIn("no longer reported", page)

    def test_a_reason_parameter_nobody_pinned_is_ignored(self):
        self._findings()
        page = self.client.get(
            "/status/site/wiz?reason=nope").get_data(as_text=True)
        self.assertNotIn("no longer reported", page)
        self.assertNotIn('id="pinned-reason"', page)

    def test_the_page_is_viewer_visible(self):
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        self.client.get("/logout")
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False
        self.assertIn("waiting on review", self._page())


class PinnedCardTests(TestCase):
    """What a pinned node's card shows, now that it keeps the check's reading.

    Four states, and they are the slice's test matrix. Before the keystone only the
    first was renderable at all: a pin overwrote the reading, so a silenced node
    could not say what it was silencing — the very transform
    [ADR-0032](../docs/adr/0032-status-contribution-boundary.md) rule 5 says a
    surface must make visible.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _pin(self, path="/site/db", reason="cutover"):
        self.client.post("/maintenance", data={
            "path": path, "action": "set", "reason": reason, "duration": "2d"})

    def _card(self):
        # `dense=0`: a pinned node reads MAINTENANCE, which is neither warn nor
        # error, so the dense grid collapses it to a chip that draws no reasons at
        # all. That case is real and covered — it is why the pip exists — but the
        # card content is what these four states are about.
        return self.client.get("/status?dense=0").get_data(as_text=True)

    def _leaf(self):
        return self.client.get("/status/site/db").get_data(as_text=True)

    def test_pinned_and_healthy_is_quiet_and_unremarkable(self):
        self.tree.upsert("/site/db", StatusCode.OK)
        self._pin()
        body = self._card()
        self.assertIn("Silenced by <strong>pan</strong>", body)
        self.assertIn("cutover", body)
        # An OK reading is named too, not suppressed. "No suffix means healthy"
        # would be a silent convention, and the whole point of the suffix is that
        # you never have to wonder what is under the blue. (The box's state
        # cluster now prints the word itself and the suffix beside it — the same
        # rendered text the single word=True span used to carry.)
        self.assertIn(
            'maintenance <span class="status-reported">· ok</span>', body)

    def test_pinned_over_an_error_names_what_it_is_silencing(self):
        # the state that was invisible before, and the reason the keystone exists
        self.tree.upsert("/site/db", StatusCode.ERROR, "disk full")
        self._pin()
        body = self._card()
        self.assertIn("status-reported", body)
        self.assertIn("· error", body)
        self.assertIn("disk full", body)          # the failure text is readable
        self.assertIn("Silenced by <strong>pan</strong>", body)
        leaf = self._leaf()
        self.assertIn("· error", leaf)
        self.assertIn("disk full", leaf)

    def test_the_reading_survives_a_write_under_the_pin(self):
        self.tree.upsert("/site/db", StatusCode.OK, "all good")
        self._pin()
        self.tree.upsert("/site/db", StatusCode.ERROR, "disk full")
        body = self._card()
        self.assertIn("disk full", body)
        self.assertNotIn("all good", body)

    def test_pinned_and_stale_says_nobody_is_checking(self):
        self.tree.upsert("/site/db", StatusCode.OK, frequency_seconds=60)
        self._pin()
        with mock.patch("little_sister.tree.datetime") as clock:
            clock.now.return_value = datetime.now() + timedelta(seconds=200)
            clock.fromisoformat = datetime.fromisoformat
            body = self._card()
        self.assertIn("status-stale", body)
        # and it stops contributing nothing: the card above it is no longer green
        self.assertIn("Silenced by <strong>pan</strong>", body)

    def test_a_pinned_branch_says_so_on_its_own_page_at_every_depth(self):
        """The one node a subtree page never described was the node whose page it is.

        The grid renders the *children*, so a pin on the viewed branch surfaced only
        through the maintenance card at the foot of the page — which is admin-only,
        so a viewer saw a green child and nothing else. And the page disagreed with
        itself: ``depth=0`` drew the node as a card with its banner, ``depth=3`` drew
        nothing.
        """
        self.tree.upsert("/site/db", StatusCode.OK)
        self._pin("/site")
        for depth in (0, 1, 3):
            with self.subTest(depth=depth):
                body = self.client.get(
                    f"/status/site?depth={depth}").get_data(as_text=True)
                grid = body.split('id="status-grid"', 1)[1].split("</main>", 1)[0]
                self.assertIn("pin-banner", grid)
                self.assertIn("Silenced by <strong>pan</strong>", grid)

    def test_a_viewer_sees_the_pin_too(self):
        # the maintenance card is `{% if is_admin %}`; the head row is not, and the
        # whole point of an indexed suppression is that everyone can see it.
        self.tree.upsert("/site/db", StatusCode.OK)
        self._pin("/site")
        self.client.get("/logout")
        with self.client.session_transaction() as sess:
            sess["username"], sess["firstname"], sess["admin"] = "vera", "Vera", False
        body = self.client.get("/status/site?depth=3").get_data(as_text=True)
        self.assertIn("Silenced by <strong>pan</strong>", body)
        self.assertNotIn('text-uppercase">Maintenance<', body)   # no admin card

    def test_an_unremarkable_container_page_adds_no_head_row(self):
        # a container with no reading, no reasons and no pin has nothing of its own
        # to say, and its page should still open with its children
        self.tree.upsert("/site/db", StatusCode.OK)
        body = self.client.get("/status/site?depth=3").get_data(as_text=True)
        self.assertNotIn("viewed-head", body)

    def test_pinned_with_entry_pins_names_the_node_pin_not_the_count(self):
        self.tree.upsert("/site/wiz", StatusCode.ERROR,
                         {"a": "first finding", "b": "second finding"})
        self.client.post("/maintenance", data={
            "path": "/site/wiz", "slug": "a", "action": "set",
            "reason": "ada is on it", "duration": "2d"})
        self._pin("/site/wiz", reason="cutover")
        body = self._card()
        # the individually pinned line still stands out inside the blue card, so you
        # can see what stays silenced once the node pin is cleared
        self.assertIn("is-quiet", body)
        self.assertIn("also pinned individually", body)
        self.assertNotIn("nothing here is reporting", body)
        self.assertNotIn("1 of 2 in maintenance", body)


class DurationGuardTests(TestCase):
    """A maintenance window must be a **positive, bounded** number of seconds
    (ADR-0014). ADR-0014 promised a *finite* expiry; finite was not
    enough."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/db", StatusCode.ERROR, "boom")

    def _set(self, duration, reason="ada is on it", token=""):
        return self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": reason,
            "duration": duration, "set_at": token})

    def test_a_negative_window_is_refused_and_writes_nothing(self):
        # it used to be written happily, land in the past, and be swept away a
        # tick later — taking the reason and both authorships with it
        response = self._set("-1d")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", body)
        self.assertIn("has to be in the future", body)
        self.assertIn('placeholder="why?">ada is on it</textarea>', body)
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_zero_is_refused_too(self):
        self.assertIn("is not a duration or expiry",
                      self._set("0").get_data(as_text=True))
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_a_window_longer_than_a_year_is_refused(self):
        body = self._set("400d").get_data(as_text=True)
        self.assertIn("longer than a year", body)
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_the_durations_that_used_to_500(self):
        for duration in ("inf", "1e20", "99999999d", "6 hours", "nan"):
            with self.subTest(duration=duration):
                response = self._set(duration)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Nothing was saved",
                              response.get_data(as_text=True))
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_a_refusal_keeps_the_token_so_a_retry_lands(self):
        self._set("2h")
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        body = self._set("-1d", reason="fixed", token=entry.set_at).get_data(
            as_text=True)
        # nothing about the stored pin moved, so the form carries the same token
        self.assertIn(f'name="set_at" value="{entry.set_at}"', body)
        self.assertEqual(self.tree.maintenance_entry("/db").reason,
                         "ada is on it")

    def test_the_year_boundary_is_inclusive(self):
        self.assertEqual(self._set("365d").status_code, 302)
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None

    def test_one_second_is_allowed(self):
        self.assertEqual(self._set("1s").status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/db"))

    def test_a_blank_duration_still_means_the_configured_default(self):
        self.assertEqual(self._set("").status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/db"))

    def test_an_entry_pin_is_guarded_the_same_way(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, {"f-1": "one"})
        response = self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set",
            "reason": "on it", "duration": "-1d", "set_at": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.tree.entry_maintenance("/wiz", "f-1"))

    def test_a_calendar_expiry_pins_an_entry_too(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, {"f-1": "one"})
        tomorrow = datetime.now(app_module.config.tzinfo) + timedelta(days=1)
        response = self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set",
            "reason": "on it",
            "duration": tomorrow.strftime("%Y-%m-%d %H:%M:%S"),
            "set_at": ""})
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.tree.entry_maintenance("/wiz", "f-1"))

    def test_a_calendar_expiry_uses_the_same_node_write(self):
        tomorrow = datetime.now(app_module.config.tzinfo) + timedelta(days=1)
        response = self._set(tomorrow.strftime("%Y-%m-%d %H:%M:%S"))
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/db"))

    def test_a_refused_expiry_keeps_the_raw_value_and_help(self):
        body = self._set("32").get_data(as_text=True)
        self.assertIn('name="duration" value="32"', body)
        self.assertIn("Which formats can I use?", body)
        # the grammar is visible at the field (ADR-0014), weeks included
        self.assertIn("<code>1w</code>", body)
        self.assertIn("Nothing was saved", body)

    def test_a_week_is_a_duration_here_too(self):
        self.assertEqual(self._set("1w").status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/db"))

    def test_a_capital_m_is_refused_with_its_own_sentence(self):
        # `6M` used to lowercase into six *minutes* and the pin was gone before
        # anyone looked; it is refused by name, and the words come back
        body = self._set("6M").get_data(as_text=True)
        self.assertIn("Nothing was saved", body)
        self.assertIn("M is not a unit", body)
        self.assertIn("m is minutes", body)
        self.assertIn('name="duration" value="6M"', body)
        self.assertIsNone(self.tree.maintenance_entry("/db"))


class _Scheduled:
    """What the floor reads off a configured check: where it sits and how often
    it runs."""

    def __init__(self, path: str, frequency_seconds: int) -> None:
        self.path = path
        self.frequency_seconds = frequency_seconds


class IntervalFloorTests(TestCase):
    """A window shorter than the interval of the check it covers is refused
    (ADR-0014): the pin would end before that check runs again, so it would cover
    no run of what it names — whichever spelling produced the window."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self.tree.upsert("/payments/api", StatusCode.OK, "fine")
        self.tree.upsert("/payments/reconcile", StatusCode.OK, "fine")
        app_module.engine = mock.Mock(checks=[
            _Scheduled("/db", 300),
            _Scheduled("/payments/api", 60),
            _Scheduled("/payments/reconcile", 1200),
        ])
        self.addCleanup(setattr, app_module, "engine", None)

    def _set(self, path, duration, slug=""):
        return self.client.post("/maintenance", data={
            "path": path, "action": "set", "reason": "ada is on it",
            "duration": duration, "set_at": "", "slug": slug})

    def test_a_window_shorter_than_the_interval_is_refused_and_names_it(self):
        body = self._set("/db", "2m").get_data(as_text=True)
        self.assertIn("Nothing was saved", body)
        self.assertIn("&#39;2m&#39; ends before /db (every 5m) runs again", body)
        self.assertIn("Use at least 5m", body)
        self.assertIn('name="duration" value="2m"', body)
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_a_window_equal_to_the_interval_passes(self):
        # one run lands inside it
        self.assertEqual(self._set("/db", "5m").status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/db"))

    def test_a_calendar_spelling_is_measured_the_same_way(self):
        # 18:00 typed at 17:59 is a sixty-second window, however it was spelled
        soon = datetime.now(app_module.config.tzinfo) + timedelta(seconds=90)
        body = self._set("/db", soon.strftime("%Y-%m-%d %H:%M:%S")).get_data(
            as_text=True)
        self.assertIn("ends before /db (every 5m) runs again", body)
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_a_container_pin_has_to_clear_the_slowest_check_it_covers(self):
        body = self._set("/payments", "5m").get_data(as_text=True)
        self.assertIn(
            "&#39;5m&#39; ends before /payments/reconcile (every 20m) runs again",
            body)
        self.assertIsNone(self.tree.maintenance_entry("/payments"))
        self.assertEqual(self._set("/payments", "20m").status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/payments"))

    def test_an_entry_pin_is_held_to_the_same_floor(self):
        self.tree.upsert("/db", StatusCode.ERROR, {"f-1": "one"})
        body = self._set("/db", "1m", slug="f-1").get_data(as_text=True)
        self.assertIn("ends before /db (every 5m) runs again", body)
        self.assertIsNone(self.tree.entry_maintenance("/db", "f-1"))

    def test_a_leaf_below_a_branch_check_answers_to_the_check_above_it(self):
        app_module.engine = mock.Mock(checks=[_Scheduled("/host", 600)])
        self.tree.upsert("/host/disk", StatusCode.OK, "fine")
        body = self._set("/host/disk", "1m").get_data(as_text=True)
        self.assertIn("ends before /host (every 10m) runs again", body)
        self.assertIsNone(self.tree.maintenance_entry("/host/disk"))

    def test_a_blank_field_keeps_the_configured_default_whatever_the_interval(self):
        # the one value that never refuses (ADR-0014): the default is the
        # deployment's own, and a settings typo must not make the form unusable
        app_module.engine = mock.Mock(checks=[_Scheduled("/db", 30 * 86400)])
        self.assertEqual(self._set("/db", "").status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry("/db"))

    def test_a_path_no_check_covers_keeps_the_one_second_floor(self):
        self.tree.upsert("/elsewhere", StatusCode.OK, "fine")
        self.assertEqual(self._set("/elsewhere", "1s").status_code, 302)

    def test_without_an_engine_the_one_second_floor_stays(self):
        app_module.engine = None
        self.assertEqual(self._set("/db", "1s").status_code, 302)


class MaintenanceExpiryInputTests(TestCase):
    """The form accepts a small deterministic calendar grammar and resolves every
    spelling to the existing naive server-local expiry."""

    zone = ZoneInfo("Europe/Berlin")

    def _resolve(self, value: str, now: datetime) -> datetime:
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, timezone="Europe/Berlin")):
            return app_module._maintenance_expiry(value, now=now)

    @staticmethod
    def _stored(moment: datetime) -> datetime:
        return moment.astimezone().replace(tzinfo=None)

    def test_duration_and_explicit_seconds_are_elapsed_from_now(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("2h", now),
            self._stored(datetime(2026, 8, 3, 12, 0, tzinfo=UTC)))
        self.assertEqual(
            self._resolve("17s", now),
            self._stored(datetime(2026, 8, 3, 10, 0, 17, tzinfo=UTC)))
        self.assertEqual(
            self._resolve("1w", now),
            self._stored(datetime(2026, 8, 10, 10, 0, tzinfo=UTC)))

    def test_a_unit_is_lowercase_on_the_form_as_in_a_config(self):
        """The form reads exactly what the shared parser reads (ADR-0014): `2W`
        and `5H` are refused there, so they are refused here, with the help."""
        now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
        for value in ("2W", "5H", "3D"):
            with self.subTest(value=value), \
                    self.assertRaises(app_module._BadExpiry) as caught:
                self._resolve(value, now)
            self.assertIn("is not a duration or expiry", str(caught.exception))

    def test_a_bare_number_is_the_next_day_of_month(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)  # 12:00 configured time
        self.assertEqual(
            self._resolve("17", now),
            self._stored(datetime(2026, 8, 17, tzinfo=self.zone)))

        on_the_day = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("17", on_the_day),
            self._stored(datetime(2026, 9, 17, tzinfo=self.zone)))

    def test_day_of_month_skips_a_month_that_has_no_such_day(self):
        now = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("31", now),
            self._stored(datetime(2026, 7, 31, tzinfo=self.zone)))

    def test_month_day_uses_this_year_then_rolls_to_the_next(self):
        before = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("07-10", before),
            self._stored(datetime(2026, 7, 10, tzinfo=self.zone)))

        on_the_day = datetime(2026, 7, 10, 10, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("07-10", on_the_day),
            self._stored(datetime(2027, 7, 10, tzinfo=self.zone)))

    def test_full_date_and_local_or_offset_timestamp(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        self.assertEqual(
            self._resolve("2026-07-10", now),
            self._stored(datetime(2026, 7, 10, tzinfo=self.zone)))
        self.assertEqual(
            self._resolve("2026-07-10 18:00", now),
            self._stored(datetime(2026, 7, 10, 18, 0, tzinfo=self.zone)))
        self.assertEqual(
            self._resolve("2026-07-10T18:00+03:00", now),
            self._stored(datetime(2026, 7, 10, 15, 0, tzinfo=UTC)))
        self.assertEqual(
            self._resolve("2026-07-10T18:00:30Z", now),
            self._stored(datetime(2026, 7, 10, 18, 0, 30, tzinfo=UTC)))

    def test_unzoned_input_uses_configured_not_host_timezone(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
        auckland = ZoneInfo("Pacific/Auckland")
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, timezone="Pacific/Auckland")):
            resolved = app_module._maintenance_expiry("23:00", now=now)
        self.assertEqual(
            resolved,
            self._stored(datetime(2026, 8, 3, 23, 0, tzinfo=auckland)))

    def test_time_only_uses_today_or_tomorrow(self):
        before = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)  # 12:00 in Berlin
        self.assertEqual(
            self._resolve("18:00", before),
            self._stored(datetime(2026, 8, 3, 18, 0, tzinfo=self.zone)))

        after = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)   # 22:00 in Berlin
        self.assertEqual(
            self._resolve("18:00", after),
            self._stored(datetime(2026, 8, 4, 18, 0, tzinfo=self.zone)))

    def test_weekday_uses_today_only_while_its_time_is_future(self):
        # 2026-08-03 is Monday.
        morning = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("mon 14:30", morning),
            self._stored(datetime(2026, 8, 3, 14, 30, tzinfo=self.zone)))

        evening = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("Monday 14:30", evening),
            self._stored(datetime(2026, 8, 10, 14, 30, tzinfo=self.zone)))

    def test_bare_weekday_uses_the_following_weekday_at_noon(self):
        # 2026-08-03 is Monday. A bare Monday always means the following Monday,
        # independent of whether today's noon has passed.
        morning = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("monday", morning),
            self._stored(datetime(2026, 8, 10, 12, 0, tzinfo=self.zone)))

        afternoon = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)
        self.assertEqual(
            self._resolve("MON", afternoon),
            self._stored(datetime(2026, 8, 10, 12, 0, tzinfo=self.zone)))
        self.assertEqual(
            self._resolve("Friday", morning),
            self._stored(datetime(2026, 8, 7, 12, 0, tzinfo=self.zone)))

    def test_dst_hole_and_fold_need_an_explicit_offset(self):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        for value in ("2026-03-29 02:30", "2026-10-25 02:30"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                        app_module._BadExpiry, "not an unambiguous local time"):
                    self._resolve(value, now)

        self.assertEqual(
            self._resolve("2026-10-25T02:30+02:00", now),
            self._stored(datetime(2026, 10, 25, 0, 30, tzinfo=UTC)))

    def test_invalid_ambiguous_and_out_of_range_values_are_refused(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
        for value in ("32", "02-30", "Funday", "10-07-2026", "90"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                        app_module._BadExpiry, "not a duration or expiry"):
                    self._resolve(value, now)
        with self.assertRaisesRegex(app_module._BadExpiry, "in the future"):
            self._resolve("2026-08-01", now)
        with self.assertRaisesRegex(app_module._BadExpiry, "longer than a year"):
            self._resolve("2027-08-04 14:00", now)

    def test_the_exact_365_day_boundary_is_inclusive(self):
        now = datetime(2026, 1, 1, tzinfo=UTC)
        with mock.patch.object(
                app_module, "config", replace(app_module.config, timezone="UTC")):
            resolved = app_module._maintenance_expiry(
                "2027-01-01 00:00", now=now)
        self.assertEqual(resolved, self._stored(datetime(2027, 1, 1, tzinfo=UTC)))


class BlankReasonTests(TestCase):
    """A blank reason on an **edit** means "I did not touch this field"."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/db", StatusCode.ERROR, "boom")

    def _pin(self, reason="the real explanation"):
        self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": reason,
            "duration": "2h", "set_at": ""})
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        return entry

    def test_an_edit_that_only_changes_the_window_keeps_the_reason(self):
        first = self._pin()
        self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "",
            "duration": "3d", "set_at": first.set_at})
        after = self.tree.maintenance_entry("/db")
        assert after is not None
        self.assertEqual(after.reason, "the real explanation")
        self.assertNotEqual(after.expires_at, first.expires_at)

    def test_a_new_pin_with_no_reason_still_says_maintenance(self):
        # nothing to keep, so the literal placeholder is the honest answer
        self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "",
            "duration": "2h", "set_at": ""})
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.reason, "maintenance")

    def test_a_typed_reason_still_replaces(self):
        first = self._pin()
        self.client.post("/maintenance", data={
            "path": "/db", "action": "set", "reason": "new words",
            "duration": "2h", "set_at": first.set_at})
        self.assertEqual(self.tree.maintenance_entry("/db").reason, "new words")

    def test_an_entry_pin_keeps_its_reason_the_same_way(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, {"f-1": "one"})
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set",
            "reason": "ada is on it", "duration": "2h", "set_at": ""})
        first = self.tree.entry_maintenance("/wiz", "f-1")
        assert first is not None
        self.client.post("/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set", "reason": "",
            "duration": "3d", "set_at": first.set_at})
        after = self.tree.entry_maintenance("/wiz", "f-1")
        assert after is not None
        self.assertEqual(after.reason, "ada is on it")
