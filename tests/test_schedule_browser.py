"""A series set and changed in a real browser (ADR-0150, landing 4; #35's note,
decisions 4 and 5): in the drawer, the editor's rest opening in place as a repeat is
chosen, saying what it would set as its fields change, *weekend* ticking its days and
*Add an interval* listing a window with its ×, each in place and nothing written, and
the close asking before it drops them; *Extend* and *End now* on a window open, each a
write the drawer closes on. By the keyboard: Enter in *Until* presses no preset, Escape
closes what it opened and *Keep it* the question *Clear* asks, the focus back where it
was. On a phone, the block's two rows and the editor in the sheet without a scroll
sideways.

What the server answers is ``tests/test_schedule_editor.py``'s. Served by a real server
to headless Chromium as ``tests/test_drawer_browser.py`` is, whose case and estate this
one shares, and skipped where Playwright or a Chromium binary is unavailable
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from little_sister import app as app_module
from little_sister.pins import Pin
from little_sister.schedule import WEEKDAYS, Schedule
from tests.test_drawer_browser import _ASKING, _LOADED, _OPEN, _READY, _SHUT
from tests.test_pin_browser import _EDITING, _BrowserCase
from tests.test_seen_browser import _wall

BERLIN = ZoneInfo("Europe/Berlin")
#: The block the frame's page landed at, planned.
_AT_PLANNED = ("(function () { var f = document.querySelector('.ls-drawer__frame');"
               " var d = f && f.contentDocument; var at = d && d.getElementById('at');"
               " return at !== null && at.classList.contains('rule-block--planned');"
               " })()")
#: Whether the frame's page, or the page, scrolls sideways.
_SIDEWAYS = ("(function (d) { return d.documentElement.scrollWidth"
             " > d.documentElement.clientWidth + 1; })")


def _daily_open_now() -> Schedule:
    """Every day for an hour, from ten minutes ago in Berlin, for three days: its first
    window open now, fifty minutes left."""
    began = (datetime.now(UTC) - timedelta(minutes=10)).replace(microsecond=0)
    until = datetime.now(UTC) + timedelta(days=3)
    return Schedule.parse(
        f"DTSTART;TZID=Europe/Berlin:{began.astimezone(BERLIN):%Y%m%dT%H%M%S}\n"
        f"DURATION:PT1H\nRRULE:FREQ=DAILY;UNTIL={until:%Y%m%dT%H%M%S}Z")


class ScheduleBrowserTests(_BrowserCase):
    """A series set and changed from the drawer, by the keyboard and on a phone — in
    Chromium."""

    estate = staticmethod(_wall)
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1300, "height": 800}, "reduced_motion": "reduce"}

    def setUp(self) -> None:
        super().setUp()
        app_module.status_tree.on_pin_end(app_module.notes_book.pin_ended)

    # --- the hand -------------------------------------------------------------------

    def _series(self) -> Pin:
        """The uplink's daily series, its window open now."""
        write = app_module.status_tree.set_maintenance(
            "/uplink", "the router's nightly firmware check",
            schedule=_daily_open_now(), set_by="lex")
        assert write.current is not None
        return write.current

    def _open_uplink(self) -> Any:
        """The wall, and the drawer opened at the uplink's door: its page, the
        panel."""
        page = self.page
        page.goto(f"{self.base}/status")
        page.wait_for_function(_READY)
        page.locator(".status-card").filter(
            has=page.locator('.status-card__head[data-path="/uplink"]')).locator(
            '.status-card__head [data-control="door"]').first.click()
        page.wait_for_function(_OPEN)
        page.wait_for_function(_LOADED)
        return page.frame_locator(".ls-drawer__frame")

    def _window(self) -> tuple[datetime, datetime]:
        entry = app_module.status_tree.maintenance_entry("/uplink")
        assert entry is not None
        opened = app_module.status_tree.open_series(entry)
        assert opened is not None
        return opened.window.start, opened.window.end

    def _focused(self, page: Any = None) -> str:
        """What has the focus, as a selector would name it."""
        return str((page or self.page).evaluate(
            "(function () { var a = document.activeElement;"
            " var d = a.closest('details');"
            " return a.tagName.toLowerCase() + '|' + (a.getAttribute('name') || '')"
            " + '|' + (d ? d.className : ''); })()"))

    # --- the drawer -----------------------------------------------------------------

    def test_the_rest_opens_in_place_and_says_what_it_would_set(self):
        page = self.page
        frame = self._open_uplink()
        frame.locator(".ack-kind", has_text="Maintenance").click()
        form = frame.locator(".ls-kind-form[data-kind=maintenance]")
        rest = form.locator("details.ls-schedule-rest")
        self.assertIsNone(rest.get_attribute("open"), "closed for a window from now")
        label = form.locator("label[for=form-maintenance-duration]")
        self.assertEqual(label.inner_text(), "Duration or expiry")
        end = form.locator("input[name=duration]")
        zone = form.locator("#form-maintenance-expiry-zone")
        self.assertTrue(end.get_attribute("placeholder").startswith(
            "e.g. 2h or Friday"))
        self.assertTrue(zone.is_visible())
        url = page.evaluate("document.querySelector('.ls-drawer__frame')"
                            ".contentWindow.location.href")
        form.locator("textarea[name=note]").fill("the router's weekend firmware")
        form.locator("select[name=repeat]").select_option("weekly")
        self.assertIsNotNone(rest.get_attribute("open"), "a repeat opens the rest")
        self.assertEqual(label.inner_text(), "Length")
        # a length alone, in no zone: *Times in* names the one a repeat reads
        self.assertEqual(end.get_attribute("placeholder"), "a length, e.g. 8h or 1d")
        self.assertTrue(zone.is_hidden())
        self.assertEqual(form.locator(".ls-every__unit").inner_text(), "week")
        form.locator("input[name=starts]").fill("Sat 22:00")
        form.locator("input[name=duration]").fill("8h")
        until = (datetime.now(BERLIN) + timedelta(days=60)).date().isoformat()
        form.locator("input[name=until]").fill(until)
        form.locator("button[name=pick][value=weekend]").click()
        ticked = [box.get_attribute("value") for box in
                  form.locator("input[name=weekday]:checked").all()]
        self.assertEqual(ticked, ["SA", "SU"])
        sentence = form.locator(".ls-schedule-sentence")
        sentence.filter(has_text="Every Saturday and Sunday from 22:00 for 8 hours"
                        ).wait_for(timeout=5000)
        self.assertEqual(form.locator(".ls-schedule-next > li").count(), 6,
                         "five and more")
        # a window added by hand, listed with its × and taken out again, in place
        form.locator("input[name=add_begins]").fill("Tue 09:00")
        form.locator("input[name=add_ends]").fill("2h")
        form.locator("button[name=add]").click()
        item = form.locator(".ls-handmade__item")
        item.first.wait_for(timeout=5000)
        self.assertIn("A window from ", item.first.inner_text())
        self.assertEqual(form.locator("input[name=add_begins]").input_value(), "")
        self.assertIsNotNone(frame.locator("form[data-ls-dirty]").first
                             .get_attribute("data-ls-dirty"))
        form.locator(".ls-handmade__drop").first.click()
        item.first.wait_for(state="detached", timeout=5000)
        self.assertEqual(page.evaluate("document.querySelector('.ls-drawer__frame')"
                                       ".contentWindow.location.href"), url,
                         "every one of them in place")
        self.assertIsNone(app_module.status_tree.standing_entry("/uplink"))
        # what was written is asked about before a close drops it
        page.locator(".ls-drawer__close").click()
        page.wait_for_function(_ASKING)
        page.locator('[data-ask="keep"]').click()
        page.wait_for_function(f"!({_ASKING})")
        form.locator(".maintenance-editor-form__actions > button[type=submit]").click()
        page.wait_for_function(_AT_PLANNED, timeout=5000)
        entry = app_module.status_tree.standing_entry("/uplink")
        assert entry is not None and entry.schedule is not None
        assert entry.schedule.rule is not None
        self.assertEqual([WEEKDAYS[day] for day in entry.schedule.rule.weekdays],
                         ["SA", "SU"])
        self.assertEqual(entry.note, "the router's weekend firmware")

    def test_an_open_one_off_s_starts_shows_once_a_repeat_is_chosen(self):
        # it must stay blank unless a repeat is chosen, whose windows to come start
        # at it; without script it stands, with its hint to leave it blank
        app_module.status_tree.set_maintenance(
            "/uplink", "a quick swap", set_by="lex",
            expires_at=datetime.now(UTC) + timedelta(hours=2))
        for script in (True, False):
            page = (self.page if script else self._signed_in(
                java_script_enabled=False, **self.drawn_in))
            page.goto(f"{self.base}/notes/uplink?at=maintenance")
            if script:
                page.wait_for_function(_EDITING)
            editor = page.locator("#at form").filter(
                has=page.locator("input[name=open_once]"))
            starts = editor.locator(".ls-starts-open-once")
            self.assertEqual(starts.count(), 1)
            if not script:
                self.assertTrue(starts.is_visible(), "without script it stands")
                continue
            self.assertTrue(starts.is_hidden(), "blank unless a repeat is chosen")
            editor.locator("select[name=repeat]").select_option("daily")
            self.assertTrue(starts.is_visible())
            editor.locator("select[name=repeat]").select_option("once")
            self.assertTrue(starts.is_hidden())

    def test_extend_and_end_now_are_writes_the_drawer_closes_on(self):
        page = self.page
        self._series()
        began, ends = self._window()
        frame = self._open_uplink()
        block = frame.locator(".rule-block--series")
        self.assertEqual(block.locator(".rule-block__head").count(), 2)
        block.locator(".rule-block__extend > summary").click()
        presets = block.locator(".rule-block__preset")
        self.assertEqual(presets.all_inner_texts(),
                         ["30 minutes", "1 hour", "2 hours", "4 hours"])
        presets.filter(has_text="1 hour").click()
        page.wait_for_function(_SHUT, timeout=5000)
        self.assertEqual(self._window(), (began, ends + timedelta(hours=1)))
        frame = self._open_uplink()
        block = frame.locator(".rule-block--series")
        self.assertIn("extended by pan",
                      block.locator(".rule-block__what").inner_text())
        block.locator(".rule-block__end > summary").click()
        block.locator(".rule-block__end button[type=submit]").click()
        page.wait_for_function(_SHUT, timeout=5000)
        self.assertIsNone(app_module.status_tree.maintenance_entry("/uplink"))
        self.assertIsNotNone(app_module.status_tree.standing_entry("/uplink"),
                             "the windows to come stand")

    # --- the keyboard ---------------------------------------------------------------

    def test_by_the_keyboard_enter_escape_and_keep_it(self):
        page = self.page
        self._series()
        began, ends = self._window()
        page.goto(f"{self.base}/notes/uplink")
        page.wait_for_function(_READY)
        extend = page.locator(".rule-block__extend > summary")
        extend.focus()
        page.keyboard.press("Enter")
        self.assertIsNotNone(page.locator(".rule-block__extend").get_attribute("open"))
        # it opens in its note, as every editor does
        page.wait_for_function("document.activeElement.tagName === 'TEXTAREA'")
        self.assertEqual(self._focused(), "textarea|note|maintenance-editor-disclosure "
                                          "rule-block__extend")
        # Enter in Until reads Until, and presses no preset
        later = (ends + timedelta(minutes=90)).astimezone(BERLIN).replace(second=0)
        page.keyboard.press("Shift+Tab")
        self.assertEqual(self._focused().split("|")[:2], ["input", "until"])
        page.keyboard.type(f"{later:%Y-%m-%d %H:%M}")
        with page.expect_navigation():
            page.keyboard.press("Enter")
        self.assertEqual(self._window(), (began, later.astimezone(UTC)))
        page.wait_for_function(_READY)
        # Escape closes what Enter opened, the focus back on it
        end = page.locator(".rule-block__end > summary")
        end.focus()
        page.keyboard.press("Enter")
        self.assertIsNotNone(page.locator(".rule-block__end").get_attribute("open"))
        page.keyboard.press("Escape")
        self.assertIsNone(page.locator(".rule-block__end").get_attribute("open"))
        self.assertEqual(self._focused().split("|")[0], "summary")
        self.assertIn("rule-block__end", self._focused())
        # the question Clear asks, and Keep it, which closes it where it was
        clear = page.locator(".rule-block__ask > summary")
        clear.focus()
        page.keyboard.press("Enter")
        question = page.locator(".rule-block__ask .rule-block__question")
        self.assertEqual(question.inner_text(), "This ends every window of the "
                                                "schedule, this one and those to come.")
        keep = page.locator(".rule-block__ask .maintenance-editor-cancel")
        keep.focus()
        page.keyboard.press("Enter")
        self.assertIsNone(page.locator(".rule-block__ask").get_attribute("open"))
        self.assertIn("rule-block__ask", self._focused())
        self.assertIsNotNone(app_module.status_tree.maintenance_entry("/uplink"),
                             "nothing ended")

    # --- the phone ------------------------------------------------------------------

    def test_on_a_phone_the_rows_and_the_editor_fit_the_sheet(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 800})
        self._series()
        frame = self._open_uplink()
        panel = page.locator(".ls-drawer__panel").bounding_box()
        assert panel is not None
        self.assertAlmostEqual(panel["width"], 390, delta=1)
        inner = page.evaluate("document.querySelector('.ls-drawer__frame')"
                              ".contentDocument.documentElement.clientWidth")
        sideways = (f"{_SIDEWAYS}(document.querySelector('.ls-drawer__frame')"
                    ".contentDocument)")
        block = frame.locator(".rule-block--series")
        self.assertFalse(page.evaluate(sideways), "the two rows wrap")
        block.locator(".rule-block__extend > summary").click()
        for preset in block.locator(".rule-block__preset").all():
            box = preset.bounding_box()
            assert box is not None
            self.assertLessEqual(box["x"] + box["width"], panel["x"] + inner + 1)
        self.assertFalse(page.evaluate(sideways), "Extend's presets wrap")
        block.locator(".rule-block__extend .maintenance-editor-cancel").click()
        block.locator(".rule-block__head--schedule .rule-block__edit > summary").click()
        rest = block.locator("details.ls-schedule-rest")
        self.assertIsNotNone(rest.get_attribute("open"), "a series opens its rest")
        block.locator("select[name=repeat]").select_option("weekly")
        self.assertTrue(block.locator(".ls-days__row").is_visible())
        self.assertFalse(page.evaluate(sideways), "the editor fits the sheet")
        days = block.locator(".ls-day").all()
        self.assertEqual(len(days), 7)
        for day in days:
            box = day.bounding_box()
            assert box is not None
            self.assertLessEqual(box["x"] + box["width"], panel["x"] + inner + 1)
