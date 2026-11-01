"""The drawer, as the server draws it (ADR-0147 decisions 3 to 5).

The *Notes* tab's panel mode, which the drawer frames: a tab asked with ``?panel=1`` is
the same page without the site's bar, rail and band, its links leaving the frame
(``<base target="_top">``) and every form it draws staying in it, sending ``panel``
and naming the panel's address as where its write comes back; whatever answers a write
from it — the tab again, a refusal, a kind's conflict page — is drawn in the panel
too, and says where it holds words a write did not take; only the routes the drawer
frames are drawn so. And the drawer itself: one on every page that draws a door to
click, outside what the refresh swaps, none on the kiosk; the poll waiting for it.
What it does in a browser is ``tests/test_drawer_browser.py``'s.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.pins import SEEN, SILENCED
from little_sister.reasons import Entry as Line
from little_sister.status import StatusCode
from little_sister.tree import SILENCED_RULE, Contribution, line_contribution
from tests.page_tree import Element, parse
from tests.test_notes_tab import _Tab

STATIC = Path(app_module.__file__).parent / "static" / "js"
TEMPLATES = Path(app_module.__file__).parent / "templates"
PANEL = "/notes/ci/pipelines?panel=1"
LATER = timedelta(days=1)


def _forms(page: Element) -> list[Element]:
    return page.all(tag="form")


def _hidden(form: Element) -> dict[str, str]:
    return {box.attrs["name"]: box.attrs.get("value", "")
            for box in form.all(tag="input") if box.attrs.get("type") == "hidden"}


class PanelTests(_Tab):
    """Decision 3: the tab's panel mode, and what answers a write from it."""

    def setUp(self) -> None:
        super().setUp()
        # a line's pin and a line's seen, whose blocks carry editors on the tab
        self.tree.set_entry_maintenance("/ci/pipelines", "docs", "planned",
                                        expires_at=datetime.now(UTC) + LATER,
                                        set_by="ada")
        write = self.tree.set_acknowledgment("/ci/pipelines", "build", SEEN, "known",
                                             expires_at=None, set_by="ada")
        assert write.current is not None, write.problem

    def body(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def test_the_panel_is_the_tab_without_the_bar_the_rail_and_the_band(self):
        tab = parse(self.body("/notes/ci/pipelines"))
        self.assertEqual(len(tab.all("ls-bar")), 1)
        self.assertEqual(len(tab.all("ls-rail")), 1)
        self.assertEqual(len(tab.all("ls-band")), 1)
        self.assertEqual(tab.all(tag="base"), [])
        self.assertNotIn("data-ls-panel", tab.one(tag="body").attrs)
        panel = parse(self.body(PANEL))
        self.assertEqual(panel.all("ls-bar"), [])
        self.assertEqual(panel.all("ls-rail"), [])
        self.assertEqual(panel.all("ls-band"), [])
        self.assertEqual(panel.one(tag="base").attrs, {"target": "_top"})
        body = panel.one(tag="body")
        self.assertIn("data-ls-panel", body.attrs)
        self.assertNotIn("data-ls-mine", body.attrs)
        # the same tab: what fails, what stands and the form
        for part in ("ls-tab__fails", "ls-tab__stands", "ls-tab__form"):
            self.assertEqual(len(panel.all(part)), 1, part)

    def test_every_form_stays_in_the_frame_and_comes_back_to_the_panel(self):
        panel = parse(self.body(PANEL))
        forms = _forms(panel)
        kinds = {form.attrs.get("data-kind") for form in panel.all("ls-kind-form")}
        self.assertEqual(kinds, {"note", "seen", "silenced", "maintenance"})
        # the blocks' editors and their *Clear*, beside the form's kinds
        self.assertGreaterEqual(len(forms), len(kinds) + 4)
        for form in forms:
            self.assertEqual(form.attrs.get("target"), "_self", form)
            fields = _hidden(form)
            self.assertEqual(fields.get("panel"), "1", form)
            self.assertEqual(fields.get("next"), PANEL, form)
        # outside the panel the tab's forms are as they were
        for form in _forms(parse(self.body("/notes/ci/pipelines"))):
            self.assertNotIn("target", form.attrs)
            self.assertNotIn("panel", _hidden(form))
            self.assertNotEqual(_hidden(form).get("next"), PANEL)

    def test_a_write_from_the_panel_comes_back_to_the_panel(self):
        answer = self.client.post("/notes/ci/pipelines", data={
            "action": "add", "slug": "", "text": "a word", "panel": "1",
            "next": PANEL})
        self.assertEqual((answer.status_code, answer.headers["Location"]),
                         (302, PANEL))
        answer = self.client.post("/pins/seen", data={
            "path": "/ci/pipelines", "slug": "lint", "action": "set", "set_at": "",
            "note": "known", "next": PANEL, "from": "notes", "panel": "1"})
        self.assertEqual((answer.status_code, answer.headers["Location"]),
                         (302, PANEL))
        # a note's form that names nowhere comes back to the tab, as it always did
        answer = self.client.post("/notes/ci/pipelines", data={
            "action": "add", "slug": "", "text": "another"})
        self.assertEqual(answer.headers["Location"], "/notes/ci/pipelines")

    def test_a_refusal_from_the_panel_is_drawn_in_it_with_the_words_marked(self):
        answer = self.client.post("/pins/silenced", data={
            "path": "/ci/pipelines", "slug": "lint", "action": "set", "set_at": "",
            "note": "it flaps", "deadline": "45d", "level": "ok", "next": PANEL,
            "from": "notes", "panel": "1"})
        self.assertEqual(answer.status_code, 200)
        page = parse(answer.get_data(as_text=True))
        self.assertEqual(page.all("ls-bar"), [])
        body = page.one(tag="body")
        self.assertIn("data-ls-panel", body.attrs)
        self.assertIn("data-ls-mine", body.attrs)
        self.assertEqual(len(page.all("ls-notes__refused")), 1)
        for form in _forms(page):
            self.assertEqual(form.attrs.get("target"), "_self", form)
            self.assertEqual(_hidden(form).get("panel"), "1", form)
        # a refusal that gives no words back has none to mark
        answer = self.client.post("/notes/ci/pipelines", data={
            "action": "add", "slug": "", "text": "  ", "panel": "1", "next": PANEL})
        body = parse(answer.get_data(as_text=True)).one(tag="body")
        self.assertIn("data-ls-panel", body.attrs)
        self.assertNotIn("data-ls-mine", body.attrs)

    def test_a_kind_s_conflict_page_is_drawn_in_the_panel_its_ways_back_in_it(self):
        # a block's editor, drawn before somebody changed its pin
        answer = self.client.post("/pins/maintenance", data={
            "path": "/ci/pipelines", "slug": "docs", "action": "set",
            "set_at": "an older token",
            "note": "mine", "duration": "2h", "next": PANEL, "panel": "1"})
        self.assertEqual(answer.status_code, 200)
        page = parse(answer.get_data(as_text=True))
        self.assertEqual(page.all("ls-bar"), [])
        self.assertIn("data-ls-mine", page.one(tag="body").attrs)
        forms = _forms(page)
        self.assertTrue(forms)
        for form in forms:
            self.assertEqual(form.attrs.get("target"), "_self", form)
            self.assertEqual(_hidden(form).get("panel"), "1", form)
            self.assertEqual(_hidden(form).get("next"), PANEL, form)
        back = [link for link in page.all(tag="a") if link.attrs.get("href") == PANEL]
        self.assertTrue(back)
        for link in back:
            self.assertEqual(link.attrs.get("target"), "_self", link)

    def test_a_seen_s_refusal_page_is_drawn_in_the_panel(self):
        # a line that fails no more takes no seen
        answer = self.client.post("/pins/seen", data={
            "path": "/ci/pipelines", "slug": "docs", "action": "set", "set_at": "",
            "note": "fine", "next": PANEL, "panel": "1"})
        self.assertEqual(answer.status_code, 200)
        page = parse(answer.get_data(as_text=True))
        self.assertEqual(page.all("ls-bar"), [])
        self.assertIn("data-ls-mine", page.one(tag="body").attrs)
        for form in _forms(page):
            self.assertEqual(form.attrs.get("target"), "_self", form)
        for link in page.all(tag="a"):
            if link.attrs.get("href") == PANEL:
                self.assertEqual(link.attrs.get("target"), "_self", link)

    def test_only_the_routes_the_drawer_frames_are_drawn_so(self):
        for url in ("/status?panel=1", "/status/ci?panel=1",
                    "/history/ci/pipelines?panel=1"):
            page = parse(self.body(url))
            self.assertEqual(len(page.all("ls-bar")), 1, url)
            self.assertEqual(page.all(tag="base"), [], url)

    def test_the_panel_draws_nothing_on_a_page_outside_it(self):
        # the wall's own blocks keep their editors as they were: no target, no field
        body = self.body("/status/ci")
        self.assertNotIn('target="_self"', body)
        self.assertNotIn('name="panel"', body)


class SilenceInThePanelTests(_Tab):
    """ADR-0144 decision 1, from the drawer: a part that reads ok — a line, and a
    leaf — is silenced in the panel, and counts at the silence's level from its next
    failure."""

    def test_an_ok_line_and_an_ok_leaf_are_silenced_from_the_drawer(self):
        self.tree.upsert("/ci/jobs", StatusCode.OK, "export done")
        for door, slug in (("/notes/ci/jobs?panel=1", ""),
                           ("/notes/ci/pipelines?panel=1&reason=docs", "docs")):
            page = parse(self.client.get(door).get_data(as_text=True))
            self.assertIn("data-ls-panel", page.one(tag="body").attrs)
            form = self.form(page, SILENCED)
            self.assertTrue(self.options(form)[slug], door)
            answer = self.client.post(form.attrs["action"], data={
                **_hidden(form), "slug": slug, "note": "it flaps at night",
                "level": "warn", "deadline": "2d"})
            # back to the panel's address, which the drawer closes on
            self.assertEqual((answer.status_code, answer.headers["Location"]),
                             (302, door.split("&")[0]))
        leaf = self.tree.acknowledgment("/ci/jobs")
        line = self.tree.acknowledgment("/ci/pipelines", "docs")
        assert leaf is not None and line is not None
        self.assertEqual({(pin.kind, pin.level) for pin in (leaf, line)},
                         {(SILENCED, StatusCode.WARN)})
        # nothing changes while they read ok; a later failure counts at the level
        jobs = self.tree.snapshot("/ci/jobs")
        assert jobs is not None
        self.assertIsNone(jobs.contribution)
        self.tree.upsert("/ci/jobs", StatusCode.ERROR, "export failed")
        self.tree.upsert("/ci/pipelines", StatusCode.ERROR, [
            Line("docs", "docs failed", code=StatusCode.ERROR)], members=True)
        jobs, pipelines = (self.tree.snapshot("/ci/jobs"),
                           self.tree.snapshot("/ci/pipelines"))
        assert jobs is not None and pipelines is not None
        self.assertEqual(jobs.contribution,
                         Contribution(StatusCode.WARN, SILENCED_RULE, leaf.id))
        (docs,) = pipelines.reasons
        self.assertEqual(line_contribution(docs, pipelines),
                         Contribution(StatusCode.WARN, SILENCED_RULE, line.id))
        self.assertIs(pipelines.own_code, StatusCode.WARN)


class DrawerTests(_Tab):
    """Decisions 3 and 4: one drawer on every page that draws a door to click, outside
    what the refresh swaps — none on the kiosk — and its words."""

    def body(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def test_the_wall_a_branch_and_a_leaf_carry_one_the_refresh_never_swaps(self):
        for url in ("/status", "/status/ci", "/status/ci/jobs"):
            page = parse(self.body(url))
            drawer = page.with_id("ls-drawer")
            self.assertEqual(drawer.tag, "dialog", url)
            self.assertEqual(drawer.parent.tag if drawer.parent else "", "body", url)
            scripts = [script.attrs.get("src", "") for script in page.all(tag="script")]
            self.assertEqual(sum("js/drawer.js" in src for src in scripts), 1, url)
        self.assertNotIn("ls-drawer", self.body("/status?fragment=1"))

    def test_the_kiosk_has_none(self):
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        for url in ("/status", "/status/ci/jobs"):
            body = self.body(url)
            self.assertNotIn("ls-drawer", body, url)
            self.assertNotIn("js/drawer.js", body, url)

    def test_it_names_the_routes_it_links_its_head_to(self):
        drawer = parse(self.body("/status")).with_id("ls-drawer")
        self.assertEqual((drawer.attrs["data-notes"], drawer.attrs["data-status"]),
                         ("/notes/", "/status"))
        self.assertEqual(drawer.attrs["aria-labelledby"], "ls-drawer-title")

    def test_its_words(self):
        drawer = parse(self.body("/status")).with_id("ls-drawer")
        title = drawer.one("ls-drawer__title")
        self.assertEqual(title.attrs["id"], "ls-drawer-title")
        self.assertEqual(title.text(), "")
        links = {link.attrs["data-to"]: (link.text(), link.attrs["title"])
                 for link in drawer.all("ls-drawer__to")}
        self.assertEqual(links, {"page": ("Status", "open its page"),
                                 "tab": ("Notes", "open its tab")})
        self.assertEqual(drawer.one("ls-drawer__close").attrs["aria-label"], "Close")
        ask = drawer.one("ls-drawer__ask")
        self.assertIn("hidden", ask.attrs)
        self.assertEqual(ask.attrs["role"], "alertdialog")
        self.assertEqual(ask.one("ls-drawer__ask-words").text(),
                         "Discard what you wrote?")
        buttons = {button.attrs["data-ask"]: button.text()
                   for button in ask.all(tag="button")}
        self.assertEqual(buttons, {"discard": "Discard", "keep": "Keep writing"})
        # the frame is the script's, made at each opening
        self.assertEqual(drawer.all(tag="iframe"), [])


class ScriptTests(_Tab):
    """Decision 4: the refresh waits for the drawer as for an editor, in its one test,
    and goes on — up to date at once after a write — as the drawer says it closed."""

    def test_the_poll_waits_for_the_drawer_in_its_one_test(self):
        poll = (STATIC / "poll.js").read_text(encoding="utf-8")
        self.assertIn("var DRAWER = 'dialog.ls-drawer[open]';", poll)
        self.assertIn("return document.querySelector(DRAWER) !== null ||", poll)
        self.assertIn("container.querySelector(EDITOR) !== null;", poll)
        self.assertIn("document.addEventListener('ls:drawer'", poll)

    def test_the_pause_is_said_where_its_cause_is_and_the_stamp_keeps_its_width(self):
        # Lex's word of 2026-10-30: the stamp says *updated …* as at rest, and what
        # holds the page says *updates paused* in its own head — the stylesheet's to
        # show, on what the poll marks, so that it comes in the frame its holder
        # opens in
        poll = (STATIC / "poll.js").read_text(encoding="utf-8")
        self.assertNotIn("paused while", poll)
        self.assertIn("stamp.textContent = 'updated' + (lastOk ? ' ' + lastOk : '');",
                      poll)
        self.assertIn("document.documentElement.setAttribute('data-ls-polled', '');",
                      poll)
        self.assertIn("container.setAttribute('data-ls-poll-target', '');", poll)
        css = (STATIC.parent / "css" / "overview.css").read_text(encoding="utf-8")
        self.assertIn(
            "[data-ls-polled] .ls-drawer[open] .ls-drawer__paused,\n"
            "[data-ls-poll-target] .maintenance-editor-disclosure[open] .ls-paused"
            " { display: block; }", css)
        # and hidden everywhere else
        rule = css[css.index("\n.ls-paused {"):]
        self.assertIn("display: none;", rule[:rule.index("}")])
        # the drawer's head, under the node's name, and every block editor's form — a
        # maintenance entry's editor, an open window's Extend and End now, the
        # question a series' Clear asks (ADR-0150, landing 4) and an acknowledgment's
        drawer = parse((TEMPLATES / "_drawer.html").read_text(encoding="utf-8"))
        (line,) = drawer.all("ls-paused")
        self.assertEqual(line.text(), "updates paused")
        self.assertEqual(line.parent.attrs.get("class"), "ls-drawer__who")
        blocks = (TEMPLATES / "_rule_block.html").read_text(encoding="utf-8")
        self.assertIn('<p class="ls-paused">updates paused</p>', blocks)
        self.assertEqual(blocks.count("{{ paused_line() }}"), 5)

    def test_the_drawer_opens_from_every_door_and_says_when(self):
        drawer = (STATIC / "drawer.js").read_text(encoding="utf-8")
        self.assertIn(
            'var DOORS = "[data-control=\\"door\\"], .line-door, [data-door]";', drawer)
        self.assertIn('new CustomEvent("ls:drawer"', drawer)
        self.assertIn('src.searchParams.set("panel", "1");', drawer)


class SwitchTests(_Tab):
    """Decision 6: *◇ details*, a switch in the band beside *hide ok* and *hide idle*,
    kept in a cookie as theirs are, whose default the deployment gives, and which the
    kiosk follows; off, the wall draws none of the blocks of what handles a part, the
    page and the fragment alike, and nothing that counts goes with them."""

    def _switch(self, url: str = "/status") -> Element:
        return self.page(url).one("status-filters").with_id("handled_details")

    def test_the_band_carries_it_after_hide_idle_off_by_default(self):
        for url in ("/status", "/status/ci"):
            with self.subTest(url=url):
                band = self.page(url).one("status-filters")
                switches = [box.attrs.get("name") for box in band.all(tag="input")
                            if box.attrs.get("role") == "switch"]
                # one name for the switch, its cookie, its query parameter and its
                # default: `details` alone names a node's details (ADR-0133)
                self.assertEqual(switches, ["hide_ok", "hide_idle", "handled_details"])
                switch = band.with_id("handled_details")
                self.assertEqual(switch.attrs.get("value"), "1")
                self.assertIn("data-ls-submit", switch.attrs)
                self.assertNotIn("checked", switch.attrs)
                (label,) = [label for label in band.all(tag="label")
                            if label.attrs.get("for") == "handled_details"]
                self.assertEqual(label.text(), "details")
                self.assertEqual(
                    label.attrs.get("title"),
                    "Show who handles a part, until when and why, on the wall")
                self.assertEqual(len(label.all("handled-mark", tag="svg")), 1)

    def test_set_it_is_kept_and_said_checked(self):
        response = self.client.get("/status?view=1&handled_details=1")
        self.assertIn("handled_details=1",
                      " ".join(response.headers.getlist("Set-Cookie")))
        self.assertIn("checked", self._switch().attrs)
        # the poll's fragment keeps nothing, and is drawn as the cookie says
        fragment = self.client.get("/status?fragment=1")
        self.assertEqual(fragment.headers.getlist("Set-Cookie"), [])
        self.client.get("/status?view=1")
        self.assertNotIn("checked", self._switch().attrs)

    def test_off_the_wall_and_its_fragment_draw_no_block_and_count_the_same(self):
        self.tree.set_maintenance("/ci/jobs", "export rerun",
                                  expires_at=datetime.now(UTC) + LATER, set_by="lex")
        for url in ("/status", "/status?fragment=1"):
            with self.subTest(url=url):
                off = self.client.get(url).get_data(as_text=True)
                self.client.set_cookie("handled_details", "1")
                on = self.client.get(url).get_data(as_text=True)
                self.client.delete_cookie("handled_details")
                self.assertNotIn("rule-block", off)
                self.assertIn("rule-block--door", on)
                # the doors say the same either way — /ci's, and its box's
                door = 'title="Handle it — 1 handled: 1 node in maintenance"'
                self.assertEqual((off.count(door), on.count(door)), (2, 2))

    def test_the_kiosk_takes_the_deployments_default_alone(self):
        self.tree.set_maintenance("/ci/jobs", "export rerun",
                                  expires_at=datetime.now(UTC) + LATER, set_by="lex")
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        self.client.set_cookie("handled_details", "1")
        drawn = self.client.get("/status").get_data(as_text=True)
        self.assertNotIn("rule-block", drawn)
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, handled_details=True)):
            self.client.set_cookie("handled_details", "0")
            kiosk = self.page("/status")
        (block,) = kiosk.all("rule-block")
        self.assertEqual(block.tag, "div")
        self.assertNotIn("href", block.attrs)
