"""The editor's month in a real browser (ADR-0150, landing 5; #35's note, decision 4).

With script the month's grid is one tab stop that the arrow keys move across — a day,
a week, the week's first and last day, a month and with Shift a year — paging onto the
month before or after where a move leaves this one; a day clicked, by the keyboard or
the mouse, and a page are done in place, the focus kept where it was and the form
marked as written, so that in the drawer a close asks before it drops what a click did.
On a phone a day shows its span as a bar, and the month fits the sheet. Without script
the month is buttons, every day and every page, each sending the editor back with it
done. A standing entry's editor comes without its month (ADR-0150 decision 17): on
*Handled* its *Edit* asks for it as it opens, once, and puts it in place beside what
the fields set, which is not spoken again; without script *Preview* brings it.

What the server answers is ``tests/test_schedule_month.py``'s. Served by a real server
to headless Chromium as ``tests/test_schedule_browser.py`` is, whose case and estate
this one shares, and skipped where Playwright or a Chromium binary is unavailable
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from little_sister import app as app_module
from little_sister.schedule import Schedule
from tests.test_drawer_browser import _ASKING, _LOADED, _OPEN, _READY
from tests.test_pin_browser import _BrowserCase
from tests.test_seen_browser import _wall

BERLIN = ZoneInfo("Europe/Berlin")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
#: Whether the frame's page, or the page, scrolls sideways.
_SIDEWAYS = ("(function (d) { return d.documentElement.scrollWidth"
             " > d.documentElement.clientWidth + 1; })")
#: The day that has the focus and its tabindex, or else what has it and its page.
_FOCUSED = ("(function (d) { var a = d.activeElement;"
            " return a && a.matches('button.ls-cal__day')"
            " ? a.value + '|' + a.getAttribute('tabindex')"
            " : (a ? a.tagName.toLowerCase() + '|'"
            " + (a.getAttribute('data-page') || '') : ''); })")


def _tenth() -> date:
    """The tenth of next month in Berlin: a day in the middle of a month that lies
    ahead, whatever today is."""
    today = datetime.now(BERLIN).date()
    return (today.replace(day=1) + timedelta(days=32)).replace(day=10)


def _on(day: date, months: int) -> date:
    """``day``'s day of the month ``months`` months on, or that month's last."""
    index = day.year * 12 + day.month - 1 + months
    year, month = index // 12, index % 12 + 1
    following = date(year + month // 12, month % 12 + 1, 1)
    return date(year, month, min(day.day, (following - timedelta(days=1)).day))


def _title(day: date) -> str:
    return f"{MONTHS[day.month - 1]} {day.year}"


class MonthBrowserTests(_BrowserCase):
    """The editor's month by the keyboard, in the drawer, on a phone and without
    script — in Chromium."""

    estate = staticmethod(_wall)
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1300, "height": 900}, "reduced_motion": "reduce"}

    # --- the hand -------------------------------------------------------------------

    @staticmethod
    def _typed(form: Any, day: date, *, hours: int = 2, waits: bool = True) -> None:
        """Every day from ``day`` at 22:00 for ``hours`` hours, for two months."""
        form.locator("textarea[name=note]").fill("the nightly reindex")
        form.locator("select[name=repeat]").select_option("daily")
        rest = form.locator("details.ls-schedule-rest")
        if rest.get_attribute("open") is None:
            # without script the rest is the browser's own disclosure
            rest.locator("summary").first.click()
        form.locator("input[name=starts]").fill(f"{day:%Y-%m-%d} 22:00")
        form.locator("input[name=duration]").fill(f"{hours}h")
        form.locator("input[name=until]").fill(f"{day + timedelta(days=60):%Y-%m-%d}")
        if waits:
            form.locator(".ls-schedule-sentence").filter(
                has_text=f"Every day from 22:00 for {hours} hours").wait_for(
                timeout=5000)
            form.locator(".ls-cal__title").filter(has_text=_title(day)).wait_for(
                timeout=5000)

    def _tab(self) -> Any:
        """The uplink's Notes tab, its form on *Maintenance*."""
        page = self.page
        page.goto(f"{self.base}/notes/uplink")
        page.wait_for_function(_READY)
        page.locator(".ack-kind", has_text="Maintenance").click()
        return page.locator(".ls-kind-form[data-kind=maintenance]")

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

    def _focused(self) -> str:
        return str(self.page.evaluate(f"{_FOCUSED}(document)"))

    def _press(self, key: str, value: str) -> None:
        """``key`` pressed in the grid, and the focus on the day ``value`` once it has
        moved there — in place, or once the month it is in has come."""
        self.page.keyboard.press(key)
        self.page.wait_for_function(
            f"document.activeElement && document.activeElement.value === '{value}'",
            timeout=5000)
        self.assertEqual(self._focused(), f"{value}|0", key)

    # --- the keyboard ---------------------------------------------------------------

    def test_the_month_is_one_tab_stop_the_arrow_keys_move_across(self):
        page = self.page
        form = self._tab()
        day = _tenth()
        self._typed(form, day)
        self.assertEqual(form.locator(".ls-cal__grid").get_attribute("role"), "grid")
        stops = form.locator('button.ls-cal__day[tabindex="0"]')
        self.assertEqual(stops.count(), 1)
        self.assertEqual(stops.first.get_attribute("value"), day.isoformat())
        # one tab stop: Tab leaves the grid, and Shift+Tab comes back to its day
        stops.first.focus()
        page.keyboard.press("Tab")
        self.assertNotIn(day.isoformat(), self._focused())
        page.keyboard.press("Shift+Tab")
        self.assertEqual(self._focused(), f"{day}|0")
        # a day, a week, and the week's first and last day
        self._press("ArrowRight", (day + timedelta(days=1)).isoformat())
        self._press("ArrowDown", (day + timedelta(days=8)).isoformat())
        self._press("ArrowLeft", (day + timedelta(days=7)).isoformat())
        self._press("ArrowUp", day.isoformat())
        self._press("End", (day + timedelta(days=6 - day.weekday())).isoformat())
        monday = day - timedelta(days=day.weekday())
        self._press("Home", monday.isoformat())
        self.assertEqual(form.locator('button.ls-cal__day[tabindex="0"]').count(), 1)
        # a month on, the same day of it; and a year back, as far as this month
        later = _on(monday, 1)
        self._press("PageDown", later.isoformat())
        self.assertEqual(form.locator(".ls-cal__title").inner_text(), _title(later))
        back = _on(later, -2)
        self._press("Shift+PageUp", back.isoformat())
        self.assertEqual(form.locator(".ls-cal__title").inner_text(), _title(back))
        # a day that leaves the month for the next one pages onto it
        self._press("PageDown", _on(back, 1).isoformat())
        last = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(
            days=1)
        form.locator(f'button.ls-cal__day[value="{last}"]').focus()
        self._press("ArrowRight", (last + timedelta(days=1)).isoformat())
        self.assertEqual(form.locator(".ls-cal__title").inner_text(),
                         _title(last + timedelta(days=1)))
        self.assertIsNone(app_module.status_tree.standing_entry("/uplink"))

    def test_enter_on_a_day_leaves_its_window_out_in_place_and_again_puts_it_back(self):
        page = self.page
        form = self._tab()
        day = _tenth()
        self._typed(form, day)
        url = page.url
        form.locator('button.ls-cal__day[tabindex="0"]').focus()
        page.keyboard.press("Enter")
        item = form.locator(".ls-handmade__item")
        item.first.wait_for(timeout=5000)
        self.assertEqual(item.first.inner_text().strip(),
                         f"Left out: the window from {day} 22:00:00 ×")
        page.wait_for_function(
            "document.activeElement && document.activeElement.matches("
            f"'button.ls-cal__day[value=\"{day}\"]')", timeout=5000)
        self.assertEqual(self._focused(), f"{day}|0", "the focus stays on its day")
        said = page.evaluate("document.activeElement.getAttribute('aria-label')")
        self.assertTrue(said.endswith("A click puts its window back."), said)
        self.assertEqual(page.locator("form[data-ls-dirty]").count(), 1)
        self.assertEqual(page.url, url, "in place")
        page.keyboard.press("Enter")
        item.first.wait_for(state="detached", timeout=5000)
        self.assertEqual(self._focused(), f"{day}|0")
        self.assertIsNone(app_module.status_tree.standing_entry("/uplink"))

    # --- the drawer -----------------------------------------------------------------

    def test_in_the_drawer_a_click_and_a_page_are_done_in_place(self):
        page = self.page
        frame = self._open_uplink()
        frame.locator(".ack-kind", has_text="Maintenance").click()
        form = frame.locator(".ls-kind-form[data-kind=maintenance]")
        day = _tenth()
        self._typed(form, day)
        inner = "document.querySelector('.ls-drawer__frame').contentDocument"
        url = page.evaluate(f"{inner}.location.href")
        form.locator(f'button.ls-cal__day[value="{day}"]').click()
        item = form.locator(".ls-handmade__item")
        item.first.wait_for(timeout=5000)
        self.assertEqual(item.first.inner_text().strip(),
                         f"Left out: the window from {day} 22:00:00 ×")
        page.wait_for_function(f"{inner}.activeElement.value === '{day}'",
                               timeout=5000)
        form.locator('.ls-cal__page[data-page="month-after"]').click()
        later = _on(day, 1)
        form.locator(".ls-cal__title").filter(has_text=_title(later)).wait_for(
            timeout=5000)
        self.assertEqual(page.evaluate(f"{_FOCUSED}({inner})"), "button|month-after",
                         "the focus stays on the page")
        self.assertEqual(item.count(), 1, "what was clicked stays listed")
        self.assertEqual(page.evaluate(f"{inner}.location.href"), url, "in place")
        self.assertIsNone(app_module.status_tree.standing_entry("/uplink"))
        # what a click did is asked about before a close drops it
        page.locator(".ls-drawer__close").click()
        page.wait_for_function(_ASKING)
        page.locator('[data-ask="keep"]').click()
        page.wait_for_function(f"!({_ASKING})")

    # --- the phone ------------------------------------------------------------------

    def test_on_a_phone_a_day_shows_its_span_as_a_bar(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 800})
        frame = self._open_uplink()
        frame.locator(".ack-kind", has_text="Maintenance").click()
        form = frame.locator(".ls-kind-form[data-kind=maintenance]")
        day = _tenth()
        self._typed(form, day, hours=8)
        cell = form.locator(f'button.ls-cal__day[value="{day}"]')
        self.assertTrue(cell.locator(".ls-cal__bar").is_visible())
        self.assertFalse(cell.locator(".ls-cal__hours").first.is_visible(),
                         "its name still says its hours")

        def shares(value: date) -> list[tuple[float, float]]:
            """Where each part of a day's bar begins and ends, as shares of it."""
            each = form.locator(f'button.ls-cal__day[value="{value}"]')
            bar = each.locator(".ls-cal__bar").bounding_box()
            assert bar is not None
            found = []
            for part in each.locator(".ls-cal__bar > span").all():
                box = part.bounding_box()
                assert box is not None
                found.append(((box["x"] - bar["x"]) / bar["width"],
                              (box["x"] + box["width"] - bar["x"]) / bar["width"]))
            return found

        # from 22:00 to 06:00: the day's last twelfth, and the next day's first quarter
        ((begins, ends),) = shares(day)
        self.assertAlmostEqual(begins, 22 / 24, delta=0.03)
        self.assertAlmostEqual(ends, 1, delta=0.01)
        following = sorted(shares(day + timedelta(days=1)))
        self.assertEqual(len(following), 2, "its morning, and its own evening")
        self.assertAlmostEqual(following[0][0], 0, delta=0.01)
        self.assertAlmostEqual(following[0][1], 6 / 24, delta=0.03)
        sideways = (f"{_SIDEWAYS}(document.querySelector('.ls-drawer__frame')"
                    ".contentDocument)")
        self.assertFalse(page.evaluate(sideways), "the month fits the sheet")
        panel = page.locator(".ls-drawer__panel").bounding_box()
        assert panel is not None
        for each in form.locator("button.ls-cal__day").all():
            box = each.bounding_box()
            assert box is not None
            self.assertLessEqual(box["x"] + box["width"],
                                 panel["x"] + panel["width"] + 1)

    # --- a standing entry's month ---------------------------------------------------

    @staticmethod
    def _nightly(day: date) -> None:
        """The uplink's series, every night from ``day`` at 22:00 for two hours for two
        months: planned, no window of it open now."""
        until = datetime.combine(day + timedelta(days=60), datetime.min.time(), UTC)
        write = app_module.status_tree.set_maintenance(
            "/uplink", "the nightly reindex", set_by="lex", schedule=Schedule.parse(
                f"DTSTART;TZID=Europe/Berlin:{day:%Y%m%d}T220000\nDURATION:PT2H\n"
                f"RRULE:FREQ=DAILY;UNTIL={until:%Y%m%dT%H%M%S}Z"))
        assert write.current is not None

    def test_a_schedule_s_edit_asks_for_its_month_as_it_opens(self):
        page = self.page
        day = _tenth()
        self._nightly(day)
        asked: list[str] = []
        page.on("request", lambda request: (
            asked.append(request.url)
            if request.url.endswith("/pins/maintenance/preview") else None))
        page.goto(f"{self.base}/handled")
        page.wait_for_function(_READY)
        self.assertEqual(page.locator(".ls-cal").count(), 0, "drawn without its month")
        block = page.locator(".rule-block--planned")
        block.locator(".ls-schedule-said").evaluate("""said => {
            window.lsSaid = 0;
            new MutationObserver(found => { window.lsSaid += found.length; }).observe(
                said, {childList: true, subtree: true, characterData: true});
        }""")
        edit = block.locator(".rule-block__edit")
        edit.locator(":scope > summary").click()
        block.locator(".ls-cal__title").filter(has_text=_title(day)).wait_for(
            timeout=5000)
        self.assertEqual(len(asked), 1)
        self.assertEqual(block.locator(".ls-cal__grid").get_attribute("role"), "grid")
        stops = block.locator('button.ls-cal__day[tabindex="0"]')
        self.assertEqual(stops.count(), 1)
        self.assertEqual(stops.first.get_attribute("value"), day.isoformat())
        self.assertEqual(page.evaluate("window.lsSaid"), 0,
                         "what the fields set is not said again")
        # closed and opened again, it keeps its month and asks nothing more
        edit.locator(".maintenance-editor-cancel").click()
        edit.locator(":scope > summary").click()
        page.wait_for_timeout(300)                 # room for an ask that must not come
        self.assertEqual((len(asked), block.locator(".ls-cal").count()), (1, 1))
        # and a click on one of its days is done in place, as on a new window's
        url = page.url
        after = day + timedelta(days=1)
        block.locator(f'button.ls-cal__day[value="{after}"]').click()
        item = block.locator(".ls-handmade__item")
        item.first.wait_for(timeout=5000)
        self.assertEqual(item.first.inner_text().strip(),
                         f"Left out: the window from {after} 22:00:00 ×")
        self.assertEqual(page.url, url, "in place")

    # --- without script -------------------------------------------------------------

    def test_without_script_the_month_is_buttons(self):
        page = self._signed_in(java_script_enabled=False, **self.drawn_in)
        page.goto(f"{self.base}/notes/uplink")
        page.locator(".ack-kind", has_text="Maintenance").click()
        form = page.locator(".ls-kind-form[data-kind=maintenance]")
        self.assertTrue(form.is_visible(), "the kind chosen by the stylesheet alone")
        day = _tenth()
        self._typed(form, day, waits=False)
        with page.expect_navigation():
            form.locator("button[name=preview]").click()
        self.assertEqual(page.locator(".ls-cal__title").inner_text(), _title(day))
        self.assertIsNone(page.locator(".ls-cal__grid").get_attribute("role"))
        self.assertEqual(page.locator("button.ls-cal__day[tabindex]").count(), 0,
                         "every day a tab stop of its own")
        with page.expect_navigation():
            page.locator(f'button.ls-cal__day[value="{day}"]').click()
        self.assertEqual(
            page.locator(".ls-handmade__item").first.inner_text().strip(),
            f"Left out: the window from {day} 22:00:00 ×")
        later = _on(day, 1)
        with page.expect_navigation():
            page.locator('.ls-cal__page[data-page="month-after"]').click()
        self.assertEqual(page.locator(".ls-cal__title").inner_text(), _title(later))
        self.assertEqual(page.locator(".ls-handmade__item").count(), 1)
        self.assertIsNone(app_module.status_tree.standing_entry("/uplink"))

    def test_without_script_a_schedule_s_month_comes_with_preview(self):
        day = _tenth()
        self._nightly(day)
        page = self._signed_in(java_script_enabled=False, **self.drawn_in)
        page.goto(f"{self.base}/handled")
        self.assertEqual(page.locator(".ls-cal").count(), 0, "drawn without its month")
        block = page.locator(".rule-block--planned")
        block.locator(".rule-block__edit > summary").click()
        with page.expect_navigation():
            block.locator("button[name=preview]").click()
        self.assertEqual(page.locator(".ls-cal__title").inner_text(), _title(day))
        after = day + timedelta(days=1)
        with page.expect_navigation():
            page.locator(f'button.ls-cal__day[value="{after}"]').click()
        self.assertEqual(
            page.locator(".ls-handmade__item").first.inner_text().strip(),
            f"Left out: the window from {after} 22:00:00 ×")
        with page.expect_navigation():
            page.locator("button[type=submit]", has_text="Save changes").click()
        entry = app_module.status_tree.standing_entry("/uplink")
        assert entry is not None and entry.schedule is not None
        self.assertIn(f"\nEXDATE;TZID=Europe/Berlin:{after:%Y%m%d}T220000",
                      entry.schedule.text())
