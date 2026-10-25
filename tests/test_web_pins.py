"""Branch pins in the UI (ADR-0014): a card's pause mark and a branch's head.
The model, POST /pins/maintenance, persistence and the reaper always accepted a
container pin — these tests pin the surfaces down. Where each stands, and what
its editor says, is `tests/test_wall_pins.py`'s (ADR-0104)."""

import os
import re
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock, skipUnless
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.app import (
    _at_line,
    _maintenance_pins,
    _maintenance_rows,
    _MaintenancePin,
)
from little_sister.checks import Entry, Unit
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import parse

# What every editor of a pin is: the form the card at the foot of a branch's
# page and the wall's dialog once held, and a card and a branch's head hold now.
EDITOR = "maintenance-editor-form"


def _midday_tomorrow() -> datetime:
    """Tomorrow at midday in the configured timezone: a calendar expiry a test types
    as a wall time, which no clock change reaches — one typed in the hour a change
    repeats or skips is refused as ambiguous."""
    tomorrow = datetime.now(app_module.config.tzinfo) + timedelta(days=1)
    return tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)


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

    # ----- a card's pin mark -----

    def test_admin_card_head_carries_the_pin_mark_and_the_page_one_editor(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('data-control="pin"', body)
        self.assertIn('aria-label="set maintenance for /system"', body)
        # the mark is a link to the node's page, which the script turns into the
        # control that clones the page's one editor into the card's panel: no
        # dialog to script, and no editor in every head
        self.assertNotIn('aria-haspopup="dialog"', body)
        self.assertEqual(body.count('<template id="pin-editor">'), 1)
        # one editor of a pin, the page's, beside the ringed check's (ADR-0142)
        self.assertEqual(body.count(f'class="{EDITOR} '), 2)
        self.assertEqual(body.count('action="/pins/maintenance"\n'
                                    f'          class="{EDITOR} '), 1)
        self.assertIn("<strong>Maintenance for "
                      '<span class="pin-editor__what">this node</span>.</strong>', body)
        self.assertIn("Which formats can I use?", body)
        # what the pin would cover rides on the mark, from the unfiltered tree
        self.assertRegex(
            body, r'aria-label="set maintenance for /system"[^>]*data-beneath')

    def test_viewer_sees_no_pin_mark_and_no_editor(self):
        self._viewer()
        self.tree.upsert("/system/alpha", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn('data-control="pin"', body)
        self.assertNotIn("pin-editor", body)
        self.assertNotIn(EDITOR, body)

    def test_kiosk_hides_the_pin_mark_even_for_admin(self):
        # the kiosk is the wall display: no chrome to click (ADR-0029)
        self._login()
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.tree.upsert("/system/alpha", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn('data-control="pin"', body)
        self.assertNotIn("pin-editor", body)
        self.assertNotIn(EDITOR, body)

    def test_the_mark_rides_the_fragment_and_the_editor_does_not(self):
        # the mark stands in what the refresh swaps, so the fragment brings it; the
        # editor is the page's, outside the swap, so no fragment carries one
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        frag = self.client.get("/status?fragment=1").get_data(as_text=True)
        self.assertIn('data-control="pin"', frag)
        self.assertNotIn(EDITOR, frag)
        self.assertNotIn("pin-editor", frag)

    def test_a_leafs_mark_names_the_node_alone(self):
        self._login()
        self.tree.upsert("/uplink", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('aria-label="set maintenance for /uplink"', body)
        self.assertNotIn("data-beneath", body)

    def test_pinned_card_states_the_pin_and_has_no_mark(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self.tree.set_maintenance(
            "/db", "planned", expires_at=datetime.now(UTC) + timedelta(hours=2),
            set_by="pan")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("In maintenance by <strong>pan</strong> until ", body)
        self.assertIn("1h 59m left", body)
        self.assertNotIn('aria-label="set maintenance for /db"', body)

    # ----- a branch's head -----

    def test_branch_page_sets_maintenance_from_its_head(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        head = body.split('class="status-node viewed-head', 1)[1].split(
            'class="status-grid"', 1)[0]
        self.assertIn("Set maintenance</summary>", head)
        self.assertIn("<strong>Maintenance for this node.</strong>", head)
        self.assertIn("nothing under here will alarm", head)
        self.assertIn('name="path" value="system/alpha"', head)
        self.assertIn("default 7d", head)                  # the deployment default

    def test_branch_page_shows_the_current_pin(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self.tree.set_maintenance(
            "/system/alpha", "rebuild",
            expires_at=datetime.now(UTC) + timedelta(days=1), set_by="pan")
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        head = body.split('class="status-node viewed-head', 1)[1].split(
            'class="status-grid"', 1)[0]
        self.assertIn(
            "<strong>This node</strong> is in maintenance by <strong>pan</strong>",
            head)
        self.assertIn("<p>rebuild</p>", head)
        self.assertIn(">Clear<", head)

    def test_overview_root_gets_no_head(self):
        # a silence-everything form on the overview is a foot-gun; the root
        # stays curl-only
        self._login()
        self.tree.upsert("/db", StatusCode.OK)
        body = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("viewed-head", body)
        # one editor of a pin, the page's, which the script aims at the card
        # clicked — beside the ringed check's (ADR-0142)
        self.assertEqual(body.count('action="/pins/maintenance"\n'
                                    f'          class="{EDITOR} '), 1)
        self.assertIn('name="path" value=""', body)
        self.assertNotIn('name="path" value="/"', body)

    def test_viewer_branch_page_has_no_editor(self):
        self._viewer()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertNotIn(EDITOR, body)

    def test_missing_branch_page_has_no_editor(self):
        self._login()
        # nothing is pinned at the path, so its page (ADR-0116) has nothing to edit
        body = self.client.get("/status/nope").get_data(as_text=True)
        self.assertIn("ls-no-node", body)
        self.assertNotIn(EDITOR, body)

    def test_kiosk_branch_page_has_no_editor(self):
        self._login()
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertNotIn(EDITOR, body)

    def test_leaf_detail_page_sets_maintenance_from_its_status_line(self):
        # the card at the foot is gone from a leaf's page (ADR-0104); the form
        # it held opens from the status line, and tests/test_pin_block.py says
        # where
        self._login()
        self.tree.upsert("/svc/api", StatusCode.OK)
        body = self.client.get("/status/svc/api").get_data(as_text=True)
        self.assertNotIn('text-uppercase">Maintenance<', body)
        self.assertIn("Set maintenance", body)
        self.assertIn("Maintenance for this node.", body)
        self.assertIn("the check keeps running", body)     # the leaf sentence
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
        response = self.client.post("/pins/maintenance", data={
            "path": "system/alpha", "action": "set", "note": "rebuild"})
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
        response = self.client.post("/pins/maintenance", data={
            "path": "db", "action": "set", "note": "planned",
            "next": "/status?depth=2"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/status?depth=2"))

    def test_post_rejects_unsafe_next(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        for evil in ("//evil.example", "/\\evil.example", "https://evil.example"):
            with self.subTest(next=evil):
                response = self.client.post("/pins/maintenance", data={
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

    def _pin(self, path="/db", note="ada wrote this", by="ada"):
        return self.tree.set_maintenance(
            path, note, expires_at=datetime.now(UTC) + timedelta(days=1),
            set_by=by).current

    # ----- the set form is reachable, and prefilled, while pinned -----

    def test_pinned_branch_page_offers_the_prefilled_set_form(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        self._pin("/system/alpha", "rebuild")
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn("Save changes", body)                 # not only "Clear"
        self.assertIn(">Clear<", body)
        self.assertIn('id="head-maintenance-note" name="note"', body)
        self.assertIn('placeholder="why?">rebuild</textarea>', body)
        # the expiry is filled with the one an untouched edit keeps (ADR-0104
        # decision 5), which amended "blank is the default" for an edit
        entry = self.tree.maintenance_entry("/system/alpha")
        assert entry is not None
        was = app_module._expiry_input(entry.expires_at)
        self.assertIn(
            f'id="head-maintenance-duration" name="duration" value="{was}"', body)
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
        self.assertIn(
            '>Edit<span class="visually-hidden"> this node\'s maintenance</span>'
            "</summary>", body)
        self.assertIn("**Rebuild** — [runbook]", body)  # raw textarea source


    def test_both_forms_carry_the_token(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        entry = self._pin("/system/alpha")
        assert entry is not None
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertEqual(
            body.count(f'name="set_at" value="{entry.token}"'), 2)

    def test_unpinned_form_claims_nothing_is_pinned(self):
        self._login()
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        body = self.client.get("/status/system/alpha").get_data(as_text=True)
        self.assertIn('name="set_at" value=""', body)

    def test_pinned_card_carries_the_note_s_source_and_the_token(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned")
        assert entry is not None
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('placeholder="why?">planned</textarea>', body)
        # the editor names the pin it believes it is changing, and on the wall
        # Clear stands in that editor, under the same token (ADR-0135 decision 4)
        self.assertEqual(
            body.count(f'name="set_at" value="{entry.token}"'), 1)
        self.assertIn('name="action" value="clear" formnovalidate', body)
        self.assertIn("In maintenance by <strong>ada</strong>", body)

    def test_pinned_card_reads_first_and_keeps_the_raw_source_to_edit(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "See **runbook**")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn("<p>See <strong>runbook</strong></p>", body)
        self.assertIn('placeholder="why?">See **runbook**</textarea>', body)

    def test_editing_keeps_the_note_and_the_original_author(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned kernel upgrade")
        assert entry is not None
        response = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "planned kernel upgrade",
            "duration": "3d", "set_at": entry.token})
        self.assertEqual(response.status_code, 302)         # no conflict
        after = self.tree.maintenance_entry("/db")
        assert after is not None
        self.assertEqual(after.note, "planned kernel upgrade")
        self.assertEqual(after.created_by, "ada")           # who pinned it
        self.assertEqual(after.set_by, "pan")               # who edited it
        # the node never left maintenance on the way through
        self.assertEqual(self.tree.effective("/db"), StatusCode.MAINTENANCE)

    def test_node_page_names_both_authors_after_an_edit(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned")
        assert entry is not None
        self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "planned, longer",
            "duration": "3d", "set_at": entry.token})
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
        response = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "pan wrote this",
            "duration": "2h", "set_at": stale.token, "next": "/status?depth=2"})
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
        self.assertEqual(entry.note, "ben wrote this")

    def test_the_conflict_form_carries_the_refreshed_token(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        fresh = self._pin("/db", "ben wrote this", by="ben")
        assert fresh is not None
        body = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "mine",
            "set_at": stale.token}).get_data(as_text=True)
        self.assertIn(f'name="set_at" value="{fresh.token}"', body)
        self.assertNotIn(f'name="set_at" value="{stale.token}"', body)

    def test_taking_the_stored_note_is_one_click(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        fresh = self._pin("/db", "ben wrote this", by="ben")
        assert fresh is not None
        body = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "mine", "duration": "2h",
            "set_at": stale.token}).get_data(as_text=True)
        self.assertIn("Keep the stored note", body)
        self.assertIn('name="note" value="ben wrote this"', body)
        self.assertIn('name="duration" value="2h"', body)   # my window kept
        # and the click is taken: its form names the pin as it stands now
        (form,) = [form for form in parse(body).all(tag="form")
                   if "Keep the stored note" in form.text()]
        hidden = {box.attrs["name"]: box.attrs.get("value", "")
                  for box in form.all(tag="input")}
        self.assertEqual(hidden["set_at"], fresh.token)
        taken = self.client.post("/pins/maintenance", data=hidden)
        self.assertEqual(taken.status_code, 302)
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.note, "ben wrote this")
        self.assertNotEqual(entry.expires_at, fresh.expires_at)

    def test_clearing_someone_elses_pin_is_refused_too(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        fresh = self._pin("/db", "ben wrote this", by="ben")
        assert fresh is not None
        response = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "clear", "set_at": stale.token})
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Clear this pin", body)
        self.assertIn("ben wrote this", body)
        self.assertEqual(self.tree.effective("/db"), StatusCode.MAINTENANCE)
        # the form that clears it anyway names the pin as it stands now
        self.assertIn(f'name="set_at" value="{fresh.token}"', body)
        self.assertNotIn(f'name="set_at" value="{stale.token}"', body)
        cleared = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "clear", "set_at": fresh.token})
        self.assertEqual(cleared.status_code, 302)
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_a_pin_that_vanished_says_so(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "ada wrote this")
        assert stale is not None
        self.tree.clear_maintenance("/db")                  # expired, or cleared
        body = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "mine",
            "set_at": stale.token}).get_data(as_text=True)
        self.assertIn("gone — someone cleared it", body)
        self.assertIn('name="set_at" value=""', body)       # re-pin from nothing
        self.assertIn('placeholder="why?">mine</textarea>', body)  # my words survive

    def test_a_post_without_a_token_still_writes(self):
        # a hand-rolled client, never one of our forms: today's behavior
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "ada wrote this")
        response = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "scripted"})
        self.assertEqual(response.status_code, 302)
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.note, "scripted")

    def test_conflict_page_needs_admin(self):
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["admin"] = False
        response = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "set_at": "whatever"})
        self.assertEqual(response.status_code, 403)

    # ----- who set it, wherever the pin is -----

    def test_maintenance_page_names_both_authors(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self._pin("/db", "planned")
        assert entry is not None
        self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "planned, longer",
            "set_at": entry.token})
        body = self.client.get("/handled").get_data(as_text=True)
        self.assertIn("Pinned by <strong>ada</strong>", body)
        self.assertIn("Last changed by <strong>pan</strong>", body)

    def test_maintenance_page_renders_the_explanation_as_markdown(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "See **owner** and [runbook](https://ops.example/runbook)")
        body = self.client.get("/handled").get_data(as_text=True)
        self.assertIn("<strong>owner</strong>", body)
        self.assertIn('href="https://ops.example/runbook"', body)

    def test_maintenance_page_says_nothing_extra_about_an_untouched_pin(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "planned")
        body = self.client.get("/handled").get_data(as_text=True)
        self.assertIn("Pinned by <strong>ada</strong>", body)
        self.assertNotIn("Last changed by", body)

    def test_popover_names_the_last_writer(self):
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        self._pin("/db", "planned", by="ada")
        body = self.client.get("/status").get_data(as_text=True)
        self.assertIn('<span class="maintenance-pop__by">ada</span>', body)

    def test_a_note_with_quotes_survives_the_round_trip(self):
        # The stored text is rendered and mine goes back into a textarea; autoescape
        # owns both untrusted halves, so a quote cannot end either context.
        self._login()
        self.tree.upsert("/db/ping", StatusCode.OK)
        stale = self._pin("/db", "plain")
        assert stale is not None
        self._pin("/db", 'ben\'s "big" upgrade', by="ben")
        body = self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "pan's turn",
            "set_at": stale.token}).get_data(as_text=True)
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

    def test_the_pin_summary_takes_no_line_of_its_own(self):
        # it is drawn on the seat the rail keeps for it, at the line's end, so
        # the editor it opens can stand beneath the line (ADR-0104 decision 4)
        css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)
        rule = css.split(".reason-pin > summary {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", rule)
        self.assertIn("display: inline-flex", rule)

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
        response = self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "note": "ada is on it", "duration": "2d"})
        self.assertEqual(response.status_code, 302)
        snap = self.tree.snapshot("/wiz")
        self.assertEqual(snap.own_code, StatusCode.ERROR)
        self.assertEqual(snap.quiet_reasons, 1)
        body = self._page()
        self.assertIn("is-quiet", body)
        self.assertIn("ada is on it", body)
        self.assertIn("1 of 2 in maintenance", body)
        self.assertIn(
            'Clear<span class="visually-hidden"> this line\'s maintenance</span>',
            body)

    def test_a_pinned_line_can_be_edited_in_place_with_raw_markdown(self):
        self._login()
        self._findings()
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "note": "**Ada** has [ticket](https://issues.example/412)",
            "duration": "2d", "set_at": ""})
        entry = self.tree.entry_maintenance("/wiz", "acme/pr-412")
        assert entry is not None

        body = self._page()

        self.assertIn("<strong>Ada</strong>", body)
        self.assertIn('href="https://issues.example/412"', body)
        self.assertIn(
            '>Edit<span class="visually-hidden"> this line\'s maintenance</span>'
            '</summary>', body)
        self.assertIn(f'name="set_at" value="{entry.token}"', body)
        self.assertIn("**Ada** has [ticket]", body)  # untouched textarea source
        self.assertIn("Save changes", body)
        self.assertIn(
            'Clear<span class="visually-hidden"> this line\'s maintenance</span>',
            body)

    def test_silencing_every_line_says_nothing_is_reporting(self):
        self._login()
        self._findings()
        for slug in ("acme/pr-412", "acme/pr-77"):
            self.client.post("/pins/maintenance", data={
                "path": "/wiz", "slug": slug, "action": "set", "duration": "2d"})
        self.assertEqual(self.tree.snapshot("/wiz").own_code,
                         StatusCode.MAINTENANCE)
        self.assertIn("nothing here is reporting", self._page())

    def test_unsilencing_a_line(self):
        self._login()
        self._findings()
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-77", "action": "set",
            "duration": "2d"})
        entry = self.tree.entry_maintenance("/wiz", "acme/pr-77")
        assert entry is not None
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-77", "action": "clear",
            "set_at": entry.token})
        self.assertIsNone(self.tree.entry_maintenance("/wiz", "acme/pr-77"))
        self.assertEqual(self.tree.snapshot("/wiz").quiet_reasons, 0)

    def test_a_slug_with_a_slash_survives_the_round_trip(self):
        # the natural slug for a discovered entry has one, which is why addressing
        # is a form field / query parameter and never a path segment
        self._login()
        self._findings()
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "duration": "2d"})
        self.assertIsNotNone(self.tree.entry_maintenance("/wiz", "acme/pr-412"))

    def test_an_entry_pin_is_guarded_like_a_node_pin(self):
        self._login()
        self._findings()
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "note": "ada is on it", "duration": "2d"})
        response = self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set",
            "note": "mine", "set_at": ""})     # I believed nothing was pinned
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", body)
        self.assertIn("ada is on it", body)
        self.assertIn('name="slug" value="acme/pr-412"', body)
        entry = self.tree.entry_maintenance("/wiz", "acme/pr-412")
        assert entry is not None
        self.assertEqual(entry.note, "ada is on it")

    def test_a_non_admin_cannot_pin_a_line(self):
        self._viewer()
        self._findings()
        response = self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "acme/pr-412", "action": "set"})
        self.assertEqual(response.status_code, 403)

    # ----- the dashboard -----

    def test_the_card_shows_the_quiet_count(self):
        self._login()
        self.tree.upsert("/site/wiz", StatusCode.ERROR,
                         {"a": "one", "b": "two"})
        self.client.post("/pins/maintenance", data={
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
    capped popover summarizes **one row per node**, ``/maintenance`` lists **every
    pin**, as a block under its node's path (ADR-0104; `test_maintenance_page.py`
    holds the page's own shape). Both are pinned down here.
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

    def _pin_line(self, path, slug, note="ada is on it"):
        return self.client.post("/pins/maintenance", data={
            "path": path, "slug": slug, "action": "set",
            "note": note, "duration": "2d"})

    def _pin_node(self, path, note="whole box", duration="3d"):
        return self.client.post("/pins/maintenance", data={
            "path": path, "action": "set", "note": note, "duration": duration})

    def _page(self):
        return self.client.get("/handled").get_data(as_text=True)

    def _dashboard(self):
        return self.client.get("/status").get_data(as_text=True)

    # ----- /maintenance: every pin, and two texts in two places -----

    def test_an_entry_pin_reaches_the_maintenance_page(self):
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        body = self._page()
        self.assertNotIn("No nodes are in maintenance", body)
        self.assertIn("/site/wiz", body)
        self.assertIn("waiting on review", body)        # what is silenced
        self.assertIn("ada is on it", body)             # why it is

    def test_the_two_texts_stand_in_two_places(self):
        # `ReasonLine.text` and `Pin.note` are not the same kind of
        # thing: the line is what the block's sentence names, and the pin's note
        # is the block's note.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        block = parse(self._page()).one("rule-block")
        said = block.one("rule-block__what").text()
        self.assertIn("waiting on review", said)
        self.assertNotIn("ada is on it", said)
        self.assertEqual(block.one("rule-block__note").text(), "ada is on it")

    def test_a_node_pin_says_it_covers_the_whole_node(self):
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self._pin_node("/db")
        self.assertIn("The whole node", self._page())

    def test_the_slug_is_never_rendered_as_text(self):
        # ADR-0036 makes it opaque; it may travel in a link, and in the field of
        # the form that changes its pin, and nowhere a reader sees it.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412")
        self.assertNotIn("acme/pr-412", parse(self._page()).text())

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
        # the pill counts the pins that stand, as *Handled* lists them — one
        # node's and three lines' — and its popover still summarizes per node
        self.assertIn('maintenance-pill__count">4<', body)
        self.assertIn('aria-label="4 handled: 1 node in maintenance, '
                      '3 lines in maintenance"', body)
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
        self._pin_line("/site/wiz", "acme/pr-412", note="ada is on it")
        self._pin_node("/site/wiz", note="whole box")
        body = self._dashboard()
        # two pins stand, the node's and its line's, in one row of the popover
        self.assertIn('maintenance-pill__count">2<', body)
        popover = body.split('data-pop-for="__all__"', 1)[1].split("</template>", 1)[0]
        self.assertEqual(popover.count("maintenance-pop__item"), 1)
        self.assertIn("+ 1 reason", body)                    # the count as a suffix
        self.assertNotIn("1 of 2 reasons", body)
        self.assertIn("whole box", body)          # the node pin's note leads
        self.assertNotIn("ada is on it", body)    # not the line's
        # and `/maintenance` still lists both, the node's own pin first
        page = self._page()
        self.assertLess(page.index("The whole node"), page.index("waiting on review"))
        self.assertIn("ada is on it", page)

    def test_the_view_types_still_order_a_nodes_pins_by_hand(self):
        # the unit-level half kept: `slot` is what puts a node's own pin ahead of
        # its entries, and it is easier to state here than to arrange in a tree.
        node_pin = _MaintenancePin(path="/site/wiz", title="", note="whole box",
                                   remaining="3d", total=2,
                                   expires_at=datetime(2026, 8, 5, tzinfo=UTC))
        entry_pin = _MaintenancePin(path="/site/wiz", title="", note="ada is on it",
                                    remaining="2d", slug="acme/pr-412",
                                    line="waiting on review", slot=0, total=2,
                                    expires_at=datetime(2026, 8, 4, tzinfo=UTC))
        rows = _maintenance_rows([node_pin], [entry_pin])
        self.assertEqual((len(rows), rows[0].pinned, rows[0].quiet), (1, True, 1))
        self.assertEqual((rows[0].note, rows[0].remaining), ("whole box", "3d"))
        pins = _maintenance_pins([node_pin], [entry_pin])
        self.assertEqual([pin.slug for pin in pins], ["", "acme/pr-412"])

    def test_the_soonest_of_a_nodes_line_pins_is_the_soonest_instant(self):
        # the row says how long the soonest has left, and soonest is asked of the
        # instants: as they are spelled, a whole second sorts after its own half
        whole = datetime(2026, 8, 4, tzinfo=UTC)
        half = whole + timedelta(milliseconds=500)
        self.assertGreater(instants.stamp(whole), instants.stamp(half))
        later = _MaintenancePin(path="/site/wiz", title="", note="ada is on it",
                                remaining="2d", expires_at=half, slug="pr-412",
                                total=2)
        sooner = _MaintenancePin(path="/site/wiz", title="", note="ben is on it",
                                 remaining="1d 23h", expires_at=whole,
                                 slug="pr-77", slot=1, total=2)
        (row,) = _maintenance_rows([], [later, sooner])
        self.assertEqual(row.remaining, "1d 23h")

    def test_several_entry_pins_name_no_single_justification(self):
        # one of three notes shown as if it were the row's is worse than none;
        # `/maintenance` carries them all.
        self._findings()
        self._pin_line("/site/wiz", "acme/pr-412", note="ada is on it")
        self._pin_line("/site/wiz", "acme/pr-77", note="ben is on it")
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
        # the path heads the node's pins and leads to the node; the line's own
        # link is the one that names it
        href = re.search(r'href="(/status/site/wiz\?[^"]*)"',
                         self._page()).group(1)
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
        self.assertNotIn('class="reason-orphan"', page)
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


class BranchLinePinTests(TestCase):
    """A branch's own lines take a pin on its own page (ADR-0036 decision 12). Its
    head lists them as a leaf's page lists its lines — in
    full, each with its record, for an admin the pause mark at its end and a pinned
    line's block beneath it — and so does its one card at depth 0; the line a page is
    asked at is marked there, and a write comes back to it.

    The node is an aspect of `aws`'s shape: its scope, `OK`, and a region that cannot
    be read, `WARN`, above a node for a pipeline that fails. Any line takes a pin,
    whatever it says, as a node does."""

    BRANCH = "/cloud/aws/codepipeline"
    URL = "/status/cloud/aws/codepipeline"
    SCOPE = "3 pipelines in scope (eu-central-1)"
    UNREAD = "read/eu-west-1"
    CANNOT = "eu-west-1: pipelines cannot be read: AccessDenied"

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert(self.BRANCH, StatusCode.WARN, [
            Entry("scope", self.SCOPE, StatusCode.OK),
            Entry(self.UNREAD, self.CANNOT, StatusCode.WARN,
                  data={"region": "eu-west-1", "error": "AccessDenied"})],
            members=True)
        self.tree.upsert(f"{self.BRANCH}/deploy", StatusCode.ERROR,
                         ["last execution Failed"])

    def _viewer(self):
        self.client.get("/logout")
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def _head(self, query=""):
        return parse(self._get(self.URL + query)).one("viewed-head")

    def _line(self, box, text):
        found = [line for line in box.all("check-reason")
                 if line.one("check-reason__body").text() == text]
        self.assertEqual(len(found), 1, text)
        return found[0]

    def _form(self, line):
        # the pause mark's, beside the ringed check's on a line that fails (ADR-0142)
        return {field.attrs.get("name"): field.attrs.get("value")
                for field in line.one("reason-pin").one(EDITOR).all(tag="input")
                if field.attrs.get("type") == "hidden"}

    def _pin(self, slug, note="ada is on it"):
        written = self.tree.set_entry_maintenance(
            self.BRANCH, slug, note,
            expires_at=datetime.now(UTC) + timedelta(days=1), set_by="ada")
        self.assertTrue(written.applied)

    # ----- what the page lists -----

    def test_the_head_lists_its_own_lines_in_full_with_their_record(self):
        head = self._head()
        self.assertEqual(
            [line.one("check-reason__body").text()
             for line in head.all("check-reason")], [self.SCOPE, self.CANNOT])
        # in full: no clamp of the wall's, which is what the cards below keep
        self.assertEqual(head.all("reason-block"), [])
        record = self._line(head, self.CANNOT).one("reason-record")
        self.assertIn("AccessDenied", record.text())
        self.assertEqual(self._line(head, self.SCOPE).all("reason-record"), [])

    def test_a_record_takes_its_lines_ink_on_a_status_fill(self):
        # A page's head is a status fill, vivid where the node fails of its own,
        # and there Bootstrap's muted gray measured 3.4:1 in the light themes and
        # 1.9:1 in the dark ones. A leaf's record stood in a pale alert and kept
        # it; a leaf's page is framed as a branch's is now (backlog #91 §3.5), its
        # lines on its head's fill, and its record takes the line's ink as well.
        record = self._line(self._head(), self.CANNOT).one("reason-record")
        self.assertFalse(record.has("text-muted"))
        self.tree.upsert("/cloud/leaf", StatusCode.WARN, [
            Entry("one", "a line of a leaf", StatusCode.WARN, data={"seen": "yes"})],
            members=True)
        leaf = parse(self._get("/status/cloud/leaf")).one("reason-record")
        self.assertFalse(leaf.has("text-muted"))

    def test_an_admin_gets_the_pause_mark_on_each_line_whatever_it_says(self):
        head = self._head()
        for text, slug in ((self.SCOPE, "scope"), (self.CANNOT, self.UNREAD)):
            with self.subTest(slug=slug):
                line = self._line(head, text)
                self.assertEqual(len(line.all("reason-pin")), 1)
                fields = self._form(line)
                self.assertEqual(
                    (fields["path"], fields["slug"], fields["action"],
                     fields["set_at"]),
                    ("cloud/aws/codepipeline", slug, "set", ""))

    def test_a_viewer_reads_the_lines_and_gets_no_control(self):
        self._viewer()
        head = self._head()
        self.assertEqual(len(head.all("check-reason")), 2)
        self.assertEqual(head.all("reason-pin"), [])
        self.assertEqual(head.all(EDITOR), [])

    def test_the_kiosk_gets_no_control(self):
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.assertNotIn('class="reason-pin"', self._get(self.URL))

    def test_its_card_at_depth_zero_lists_them_too(self):
        page = parse(self._get(self.URL + "?depth=0"))
        self.assertEqual(page.all("viewed-head"), [])
        card = page.one("status-card")
        self.assertEqual(len(card.all("reason-pin")), 2)
        self.assertIn("AccessDenied", card.one("reason-record").text())

    def test_the_overviews_card_keeps_the_walls_clamp(self):
        # the overview's one card is every node there is, not a node's own page
        self.tree.upsert("/", StatusCode.WARN, {"note": "a word of the root's"})
        card = parse(self._get("/status?depth=0")).one("status-card")
        self.assertEqual(len(card.all("reason-block")), 1)
        self.assertEqual(card.all("reason-pin"), [])

    # ----- what a pin does, and what its editor says -----

    def test_a_write_from_the_head_comes_back_to_the_page_at_its_line(self):
        head = self._head("?depth=2")
        fields = self._form(self._line(head, self.CANNOT))
        back = ("/status/cloud/aws/codepipeline?depth=2"
                "&reason=read%2Feu-west-1#pinned-reason")
        self.assertEqual(fields["next"], back)
        response = self.client.post("/pins/maintenance", data={
            **fields, "note": "the role is being granted", "duration": "2d"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], back)
        marked = parse(self._get(back.split("#")[0])).with_id("pinned-reason")
        self.assertTrue(marked.has("is-focused"))
        self.assertEqual(marked.one("check-reason__body").text(), self.CANNOT)

    def test_the_pin_silences_its_line_and_nothing_else(self):
        self._pin(self.UNREAD)
        snap = self.tree.snapshot(self.BRANCH)
        assert snap is not None
        self.assertEqual((snap.own_code, snap.code),
                         (StatusCode.OK, StatusCode.ERROR))
        line = self._line(self._head(), self.CANNOT)
        self.assertTrue(line.has("is-quiet"))
        block = line.one("rule-block")
        self.assertIn("ada is on it", block.text())
        self.assertIn("Clear", block.text())
        self.assertIn("1 of 2 in maintenance.",
                      self._head().one("reason-quiet-count").text())

    def test_the_last_lines_editor_says_the_nodes_beneath_still_count(self):
        def said():
            line = self._line(self._head(), self.SCOPE)
            return line.one("rule-block__scope").text()

        self.assertEqual(
            said(), "Maintenance for this line only. The other one keeps alarming.")
        self._pin(self.UNREAD)
        self.assertEqual(
            said(), "Maintenance for this line only. No other line of its own is "
                    "left to alarm, and the nodes beneath it still count.")

    def test_every_line_silenced_says_nothing_untrue_about_what_reports(self):
        self._pin("scope")
        self._pin(self.UNREAD)
        count = self._head().one("reason-quiet-count").text()
        self.assertEqual(count, "2 of 2 in maintenance.")
        snap = self.tree.snapshot(self.BRANCH)
        assert snap is not None
        self.assertIs(snap.code, StatusCode.ERROR)

    # ----- the line a page is asked at -----

    def test_the_index_and_the_pip_lead_to_the_line(self):
        self._pin(self.UNREAD)
        index = re.search(r'href="(/status/cloud/aws/codepipeline\?reason=[^"]*)"',
                          self._get("/handled")).group(1)
        pip = re.search(r'href="(/status/cloud/aws/codepipeline\?reason=[^"]*)"',
                        self._get("/status")).group(1)
        for href in (index, pip):
            with self.subTest(href=href):
                self.assertTrue(href.endswith("#pinned-reason"), href)
                url = href.split("#")[0].replace("&amp;", "&")
                head = parse(self._get(url)).one("viewed-head")
                marked = head.with_id("pinned-reason")
                self.assertTrue(marked.has("is-focused"))
                self.assertEqual(marked.one("check-reason__body").text(),
                                 self.CANNOT)

    def test_an_unasked_page_marks_nothing(self):
        self.assertNotIn('id="pinned-reason"', self._get(self.URL))

    def test_a_pin_whose_line_is_no_longer_reported_says_so(self):
        # suspended, not deleted (ADR-0036 decision 6), on a branch as on a leaf
        self._pin("read/us-east-1")
        head = self._head("?reason=read/us-east-1")
        orphan = head.with_id("pinned-reason")
        self.assertTrue(orphan.has("reason-orphan"))
        self.assertIn("no longer reported", orphan.text())

    def test_the_refresh_carries_the_controls_and_the_line_asked_for(self):
        body = self._get(self.URL + "?depth=2&reason=scope&fragment=1")
        head = parse(body).one("viewed-head")
        self.assertEqual(len(head.all("reason-pin")), 2)
        self.assertEqual(head.with_id("pinned-reason").one(
            "check-reason__body").text(), self.SCOPE)
        # and a write from what the refresh drew comes back to the page
        self.assertNotIn("fragment", self._form(self._line(head, self.CANNOT))["next"])

    def test_the_inspection_card_leaves_a_lines_controls_alone(self):
        # The card answers a node's name alone (`NAMES`, `inspect.js`), and the
        # page's own head is no toggle: it has no card, and a control within its
        # row is the control's own. The page's head keeps the rules, the setter and
        # the lines beneath its row now, as a box does (backlog #91 §3.5): the row
        # holds its toolbar's controls alone.
        script = self.client.get("/static/js/inspect.js").get_data(as_text=True)
        found = re.search(r"var NAMES = '([^']+)';", script)
        assert found is not None
        self.assertEqual(found.group(1).split(", "),
                         [".tree-chip", '[data-control="toggle"]', ".ls-strip__name"])
        self._pin(self.UNREAD)
        head = self._head()
        row = head.one("status-node__self")
        self.assertIn("data-path", row.attrs)
        self.assertEqual(row.all(tag="form") + row.all(tag="details"), [])
        self.assertGreater(len(head.all(tag="form") + head.all(tag="summary")), 0)
        controls = row.all(tag="a") + row.all(tag="button")
        self.assertGreater(len(controls), 0)
        for element in (row, *row.walk()):
            self.assertFalse(element.has("tree-chip")
                             or element.attrs.get("data-control") == "toggle",
                             element)


class AtLineTests(TestCase):
    """Where a write to one of a page's lines comes back to (`at_line`)."""

    def test_it_keeps_the_page_and_names_the_line(self):
        self.assertEqual(_at_line("/status/x?depth=2&hide_ok=1", "scope"),
                         "/status/x?depth=2&hide_ok=1&reason=scope#pinned-reason")

    def test_it_replaces_the_line_the_page_was_asked_at(self):
        self.assertEqual(_at_line("/status/x?reason=old&depth=2", "new"),
                         "/status/x?depth=2&reason=new#pinned-reason")

    def test_a_slug_is_a_query_value_whatever_it_holds(self):
        # a declared slug may hold `/`, `#`, `%` or `&` (ADR-0036 decision 12)
        self.assertEqual(_at_line("/status/x", "a/b#c%d&e"),
                         "/status/x?reason=a%2Fb%23c%25d%26e#pinned-reason")


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

    def _pin(self, path="/site/db", note="cutover"):
        self.client.post("/pins/maintenance", data={
            "path": path, "action": "set", "note": note, "duration": "2d"})

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
        self.assertIn("In maintenance by <strong>pan</strong>", body)
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
        self.assertIn("In maintenance by <strong>pan</strong>", body)
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
        with mock.patch.object(instants, "now", return_value=(
                datetime.now(UTC) + timedelta(seconds=200))):
            body = self._card()
        self.assertIn("status-stale", body)
        # and it stops contributing nothing: the card above it is no longer green
        self.assertIn("In maintenance by <strong>pan</strong>", body)

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
        # the card at depth 0 names the node in its head, so its block opens with
        # what was done to it; the head at every other depth says *This node*
        for depth, said in ((0, "In maintenance by"), (1, "is in maintenance by"),
                            (3, "is in maintenance by")):
            with self.subTest(depth=depth):
                body = self.client.get(
                    f"/status/site?depth={depth}").get_data(as_text=True)
                grid = body.split('id="status-grid"', 1)[1].split("</main>", 1)[0]
                self.assertIn('data-rule="maintenance"', grid)
                self.assertIn(f"{said} <strong>pan</strong>", grid)

    def test_a_viewer_sees_the_pin_too(self):
        # the head's buttons are an admin's; the block is not, and the whole point
        # of an indexed suppression is that everyone can see it.
        self.tree.upsert("/site/db", StatusCode.OK)
        self._pin("/site")
        self.client.get("/logout")
        with self.client.session_transaction() as sess:
            sess["username"], sess["firstname"], sess["admin"] = "vera", "Vera", False
        body = self.client.get("/status/site?depth=3").get_data(as_text=True)
        self.assertIn("is in maintenance by <strong>pan</strong>", body)
        self.assertNotIn("maintenance-editor-form", body)       # nothing to write with

    def test_an_unremarkable_container_page_heads_its_frame_with_its_row_alone(self):
        # a container with no reading, no reasons and no pin has nothing of its own
        # to say, and its page opened with its children for a reader who could not
        # pin it. A page frames its node now (backlog #91 §3.5): the head is the
        # frame's top for every reader, and for this one it is its row alone.
        self.tree.upsert("/site/db", StatusCode.OK)
        self.client.get("/logout")
        with self.client.session_transaction() as sess:
            sess["username"], sess["firstname"], sess["admin"] = "vera", "Vera", False
        body = self.client.get("/status/site?depth=3").get_data(as_text=True)
        head = parse(body).one("viewed-head")
        parts = [part for part in head.children if not isinstance(part, str)]
        self.assertEqual([part.attrs.get("class") for part in parts],
                         ["status-node__self"])

    def test_pinned_with_entry_pins_names_the_node_pin_not_the_count(self):
        self.tree.upsert("/site/wiz", StatusCode.ERROR,
                         {"a": "first finding", "b": "second finding"})
        self.client.post("/pins/maintenance", data={
            "path": "/site/wiz", "slug": "a", "action": "set",
            "note": "ada is on it", "duration": "2d"})
        self._pin("/site/wiz", note="cutover")
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

    def _set(self, duration, note="ada is on it", token=""):
        return self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": note,
            "duration": duration, "set_at": token})

    def test_a_negative_window_is_refused_and_writes_nothing(self):
        # it used to be written happily, land in the past, and be swept away a
        # tick later — taking the note and both authorships with it
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
        body = self._set("-1d", note="fixed", token=entry.token).get_data(
            as_text=True)
        # nothing about the stored pin moved, so the form carries the same token
        self.assertIn(f'name="set_at" value="{entry.token}"', body)
        self.assertEqual(self.tree.maintenance_entry("/db").note,
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
        response = self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set",
            "note": "on it", "duration": "-1d", "set_at": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.tree.entry_maintenance("/wiz", "f-1"))

    def test_a_calendar_expiry_pins_an_entry_too(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, {"f-1": "one"})
        tomorrow = _midday_tomorrow()
        response = self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set",
            "note": "on it",
            "duration": tomorrow.strftime("%Y-%m-%d %H:%M:%S"),
            "set_at": ""})
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(self.tree.entry_maintenance("/wiz", "f-1"))

    def test_a_calendar_expiry_uses_the_same_node_write(self):
        tomorrow = _midday_tomorrow()
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
    it runs — as its one unit's period (ADR-0130)."""

    def __init__(self, path: str, frequency_seconds: int) -> None:
        self.path = path
        self.frequency_seconds = frequency_seconds

    def units(self) -> tuple[Unit, ...]:
        return (Unit("", self.frequency_seconds, ""),)


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
        return self.client.post("/pins/maintenance", data={
            "path": path, "action": "set", "note": "ada is on it",
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
        # 18:00 typed at 17:59 is a sixty-second window, however it was spelled — on
        # the server's clock held at midday, since a wall time in the hour a clock
        # change repeats or skips is refused as ambiguous
        now = datetime.now(app_module.config.tzinfo).replace(
            hour=12, minute=0, second=0, microsecond=0)
        soon = now + timedelta(seconds=90)
        with mock.patch.object(instants, "now", return_value=now.astimezone(UTC)):
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
    spelling to an instant in UTC, which the tree stores as it is."""

    zone = ZoneInfo("Europe/Berlin")

    def _resolve(self, value: str, now: datetime) -> datetime:
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, timezone="Europe/Berlin")):
            return app_module._maintenance_expiry(value, now=now)

    @staticmethod
    def _stored(moment: datetime) -> datetime:
        return moment.astimezone(UTC)

    @skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
    def test_what_comes_out_is_an_instant_in_utc_on_any_machines_clock(self):
        # a wall time is the configured zone's, never the machine's: 14:30 in
        # Berlin is 12:30Z in August, on a machine six hours behind as anywhere
        now = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
        try:
            with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
                time.tzset()
                for typed, instant in (
                        ("14:30", datetime(2026, 8, 3, 12, 30, tzinfo=UTC)),
                        ("2h", datetime(2026, 8, 3, 12, 0, tzinfo=UTC)),
                        ("", datetime(2026, 8, 10, 10, 0, tzinfo=UTC)),
                        ("2026-08-17", datetime(2026, 8, 16, 22, 0, tzinfo=UTC))):
                    with self.subTest(typed=typed):
                        resolved = self._resolve(typed, now)
                        self.assertEqual(resolved, instant)
                        self.assertIs(resolved.tzinfo, UTC)
        finally:
            time.tzset()          # back to whatever the real environment says

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


class BlankNoteTests(TestCase):
    """A blank note on an **edit** means "I did not touch this field"."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/db", StatusCode.ERROR, "boom")

    def _pin(self, note="the real explanation"):
        self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": note,
            "duration": "2h", "set_at": ""})
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        return entry

    def test_an_edit_that_only_changes_the_window_keeps_the_note(self):
        first = self._pin()
        self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "",
            "duration": "3d", "set_at": first.token})
        after = self.tree.maintenance_entry("/db")
        assert after is not None
        self.assertEqual(after.note, "the real explanation")
        self.assertNotEqual(after.expires_at, first.expires_at)

    def test_the_pages_own_form_keeps_the_note_too(self):
        # A page's form names the node as the route's `branch` — no leading
        # slash — and the stored text was looked up at the path as posted, where
        # nothing is stored: a blank note from the form wrote the placeholder
        # over the explanation.
        first = self._pin()
        response = self.client.post("/pins/maintenance", data={
            "path": "db", "action": "set", "note": "",
            "duration": "3d", "set_at": first.token})
        self.assertEqual(response.status_code, 302)
        after = self.tree.maintenance_entry("/db")
        assert after is not None
        self.assertEqual(after.note, "the real explanation")

    def test_a_new_pin_with_no_note_still_says_maintenance(self):
        # nothing to keep, so the literal placeholder is the honest answer
        self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "",
            "duration": "2h", "set_at": ""})
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.note, "maintenance")

    def test_a_typed_note_still_replaces(self):
        first = self._pin()
        self.client.post("/pins/maintenance", data={
            "path": "/db", "action": "set", "note": "new words",
            "duration": "2h", "set_at": first.token})
        self.assertEqual(self.tree.maintenance_entry("/db").note, "new words")

    def test_an_entry_pin_keeps_its_note_the_same_way(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, {"f-1": "one"})
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set",
            "note": "ada is on it", "duration": "2h", "set_at": ""})
        first = self.tree.entry_maintenance("/wiz", "f-1")
        assert first is not None
        self.client.post("/pins/maintenance", data={
            "path": "/wiz", "slug": "f-1", "action": "set", "note": "",
            "duration": "3d", "set_at": first.token})
        after = self.tree.entry_maintenance("/wiz", "f-1")
        assert after is not None
        self.assertEqual(after.note, "ada is on it")
