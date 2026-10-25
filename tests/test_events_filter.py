"""The Events page is filtered by its URL (ADR-0101), read against the record's
sentences.

The log is eight transitions an hour long, oldest first, from 17:00 in the configured
zone: a NAS whose disk fills — its host, then the disk beneath it; a second NAS whose
name only begins like the first one's; a web host whose failure a pin held back, then
the pin itself; a node the configuration has since removed; a backup whose warning
damping held back and whose reason runs to two lines; and the root clearing at 18:00.
The page's clock reads 18:00 unless a test says otherwise, and each transition's time
is what an event holds: an instant.
"""
from __future__ import annotations

import html
import os
import re
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock, skipIf
from urllib.parse import parse_qs, urlsplit

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import Event, StatusTree

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)          # 17:00 in Berlin

#: The configuration the log is read in: Berlin's clock, written to the second.
SETTINGS = {"timezone": "Europe/Berlin", "time_format": "%Y-%m-%d %H:%M:%S"}

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

#: The status switches, in the order the page offers them.
STATUSES = ("error", "warn", "ok", "maintenance", "undefined")


def _stamp(minutes: float) -> datetime:
    """The instant ``minutes`` after 17:00, as an event holds its time."""
    return T0 + timedelta(minutes=minutes)


def _event(minutes: float, path: str, old: StatusCode, new: StatusCode,
           reason: list[str], held_by: str = "") -> Event:
    return Event(path=path, name=path.rsplit("/", 1)[-1], old=old, new=new,
                 reason=tuple(reason), timestamp=_stamp(minutes),
                 suppressed_by=held_by)


def _log() -> tuple[Event, ...]:
    """The log the module's docstring describes."""
    return (
        _event(0, "/hosts/nas", OK, ERROR, ["Disk nearly full"]),
        _event(10, "/hosts/nas/disk", OK, WARN, ["full: /dev/disk2"]),
        _event(20, "/hosts/nas2/disk", OK, ERROR, ["disk full"]),
        _event(30, "/hosts/web", OK, ERROR, ["connection to nas refused"],
               "maintenance"),
        _event(40, "/hosts/web", ERROR, MAINTENANCE, ["pinned for the upgrade"]),
        _event(45, "/hosts/nas/old", OK, UNDEFINED, ["removed from the configuration"]),
        _event(50, "/svc/backup", OK, WARN, ["copy slow", "disk nearly full"],
               "damping"),
        _event(60, "/", WARN, OK, ["all clear"]),
    )


LOG = _log()

#: Each transition by the reason its row shows.
NAS, DISK, NAS2, HELD = ("Disk nearly full", "full: /dev/disk2", "disk full",
                         "connection to nas refused")
PIN, REMOVED, BACKUP, ROOT = ("pinned for the upgrade",
                              "removed from the configuration",
                              "copy slow; disk nearly full", "all clear")

#: The whole log as the page lists it, newest first.
EVERY = [ROOT, BACKUP, REMOVED, PIN, HELD, NAS2, DISK, NAS]

#: Every switch of both groups on, as a form with nothing turned off submits them.
ALL_ON = "&".join([*(f"status={code}" for code in STATUSES), "held=no", "held=yes"])


def _words(markup: str) -> str:
    """What a stretch of markup says: its text, tags dropped, spaces collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _rows(body: str) -> list[str]:
    """Each event row's reason, in the page's order."""
    rows = re.findall(r'<tr class="row-[^"]*">(.*?)</tr>', body, re.S)
    return [_words(re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)[3]) for row in rows]


def _inputs(body: str, name: str) -> list[dict[str, str]]:
    """Each ``<input>`` named ``name``, by its attributes — one without a value, such
    as ``checked``, maps to the empty string."""
    found = []
    for tag in re.findall(r"<input\b([^>]*)>", body):
        attributes = {key: html.unescape(value)
                      for key, value in re.findall(r'([\w-]+)(?:="([^"]*)")?', tag)}
        if attributes.get("name") == name:
            found.append(attributes)
    return found


def _on(body: str, name: str) -> set[str]:
    """The values of the switches named ``name`` that are on."""
    return {switch["value"] for switch in _inputs(body, name) if "checked" in switch}


def _line(body: str) -> str:
    """The line beneath the bar that says how many events there are, and match."""
    line = re.search(r'<p class="ls-events__count"[^>]*>(.*?)</p>', body, re.S)
    assert line is not None, "no count line"
    return _words(line.group(1))


def _has_reset(body: str) -> bool:
    return re.search(r'<a\b[^>]*href="/events"[^>]*>\s*reset\s*</a>', body) is not None


def _bar(body: str) -> str:
    nav = re.search(r'<nav class="ls-window"[^>]*>(.*?)</nav>', body, re.S)
    assert nav is not None, "no window bar"
    return nav.group(1)


def _range(body: str) -> str:
    """The window as the bar names it."""
    named = re.search(r'<p class="ls-window__range">(.*?)</p>', _bar(body), re.S)
    assert named is not None
    return _words(named.group(1))


def _controls(body: str) -> dict[str, str]:
    """The bar's controls by their words, each with where it leads — the empty string
    for one shown disabled."""
    controls = {}
    for attributes, words in re.findall(r"<a\b([^>]*)>(.*?)</a>", _bar(body), re.S):
        href = re.search(r'href="([^"]*)"', attributes)
        controls[_words(words)] = html.unescape(href.group(1)) if href else ""
    return controls


def _presets(body: str) -> list[str]:
    group = re.search(r'aria-label="Presets">(.*?)</div>', _bar(body), re.S)
    assert group is not None
    return [_words(words) for words in re.findall(r"<a\b[^>]*>(.*?)</a>",
                                                  group.group(1), re.S)]


def _query(href: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(href).query)


class EventsFilterTests(TestCase):
    """The filters, the window, and what the page says about both."""

    def setUp(self) -> None:
        self._saved = app_module.status_tree
        self.addCleanup(self._restore)
        self.tree = StatusTree()
        # Every node the log names still stands, except the one removed since.
        for path in ("/hosts/nas", "/hosts/nas/disk", "/hosts/nas2/disk",
                     "/hosts/web", "/svc/backup"):
            self.tree.upsert(path, OK)
        self.tree.restore_events(LOG)
        app_module.status_tree = self.tree
        settings = mock.patch("little_sister.config.config",
                              replace(app_module.config, **SETTINGS))
        settings.start()
        self.addCleanup(settings.stop)
        self.clock(60)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree = self._saved

    def clock(self, minutes: float) -> None:
        """Set the page's clock ``minutes`` after 17:00."""
        patch = mock.patch.object(app_module, "_now",
                                  return_value=T0 + timedelta(minutes=minutes))
        patch.start()
        self.addCleanup(patch.stop)

    def _get(self, url: str, status: int = 200) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)

    # --- decision 1: the filters are the page's URL, and nothing remembers them ----

    def test_the_records_example_is_a_link_to_what_it_names(self) -> None:
        body = self._get("/events?under=/hosts/nas&words=disk+full&status=error"
                         "&status=warn&held=no&from=now-6h")
        self.assertEqual(_rows(body), [DISK, NAS])

    def test_nothing_remembers_a_filter(self) -> None:
        filtered = self.client.get("/events?under=/hosts/nas&words=disk&status=error"
                                   "&held=no&from=now-15m")
        self.assertEqual(filtered.status_code, 200)
        set_cookies = {cookie.split("=", 1)[0].strip()
                       for cookie in filtered.headers.getlist("Set-Cookie")}
        self.assertFalse(
            set_cookies & {"under", "words", "status", "held", "from", "to"},
            set_cookies)
        self.assertEqual(_rows(self._get("/events")), EVERY)

    def test_empty_fields_filter_nothing(self) -> None:
        body = self._get("/events?under=&words=")
        self.assertEqual(_rows(body), EVERY)
        self.assertEqual(_line(body), "8 events")
        self.assertFalse(_has_reset(body))

    def test_the_switches_submit_their_form_and_a_browser_without_script_has_apply(
            self) -> None:
        body = self._get("/events")
        form = re.search(r'<form\b([^>]*action="/events"[^>]*)>(.*?)</form>', body,
                         re.S)
        assert form is not None, "no filter form"
        self.assertIn('method="get"', form.group(1))
        switches = _inputs(form.group(2), "status") + _inputs(form.group(2), "held")
        self.assertEqual(len(switches), 7)
        for switch in switches:
            self.assertEqual(switch["type"], "checkbox")
            self.assertIn("data-ls-submit", switch)
        self.assertEqual(len(_inputs(form.group(2), "under")), 1)
        self.assertEqual(len(_inputs(form.group(2), "words")), 1)
        self.assertRegex(form.group(2), r'<noscript>\s*<button\b[^>]*type="submit"'
                                        r'[^>]*>\s*Apply\s*</button>\s*</noscript>')

    def test_enter_in_either_field_submits_the_form(self) -> None:
        """A form with two text fields and no submit button submits nothing on Enter
        (HTML's implicit submission), and the Apply inside ``<noscript>`` is no button
        where script runs — so the form carries a default button of its own, out of
        sight and out of the tab order."""
        body = self._get("/events")
        form = re.search(r'<form\b[^>]*action="/events"[^>]*>(.*?)</form>', body, re.S)
        assert form is not None, "no filter form"
        scripted = re.sub(r"<noscript>.*?</noscript>", "", form.group(1), flags=re.S)
        default = re.search(r'<button\b[^>]*type="submit"[^>]*>', scripted)
        assert default is not None, "no submit button where script runs"
        self.assertIn('tabindex="-1"', default.group(0))

    def test_the_fields_show_what_the_url_says_and_escape_it(self) -> None:
        body = self._get("/events?under=/hosts/nas&words=%3Cb%3E+%22x%22")
        self.assertEqual(_inputs(body, "under")[0]["value"], "/hosts/nas")
        self.assertEqual(_inputs(body, "words")[0]["value"], '<b> "x"')
        self.assertNotIn('<b> "x"', body)

    def test_what_the_page_cannot_read_is_refused_naming_the_parameter(self) -> None:
        for query, named, words in (("status=bogus", "status", STATUSES),
                                    ("status=error&status=red", "status", STATUSES),
                                    ("held=maybe", "held", ("yes", "no")),
                                    ("from=yesterday", "from", ())):
            with self.subTest(query=query):
                body = self._get(f"/events?{query}", status=400)
                self.assertIn(f"<code>{named}</code>", body)
                for word in words:
                    self.assertIn(f"<code>{word}</code>", body)

    # --- decision 2: `under` is a node and everything beneath it; `words` -----------

    def test_under_is_a_node_and_everything_beneath_it(self) -> None:
        for written in ("/hosts/nas", "hosts/nas", "/hosts/nas/"):
            with self.subTest(under=written):
                self.assertEqual(_rows(self._get(f"/events?under={written}")),
                                 [REMOVED, DISK, NAS])

    def test_under_the_root_is_every_node_and_filters_nothing(self) -> None:
        body = self._get("/events?under=/")
        self.assertEqual(_rows(body), EVERY)
        self.assertEqual(_line(body), "8 events")
        self.assertFalse(_has_reset(body))

    def test_a_node_removed_since_is_found_under_the_path_it_was_recorded_at(
            self) -> None:
        self.assertIsNone(self.tree.snapshot("/hosts/nas/old"))
        self.assertEqual(_rows(self._get("/events?under=/hosts/nas/old")), [REMOVED])

    def test_each_word_is_found_in_the_reason_in_any_order_ignoring_case(
            self) -> None:
        for written in ("disk+full", "FULL+Disk", "+full+++disk+"):
            with self.subTest(words=written):
                self.assertEqual(_rows(self._get(f"/events?words={written}")),
                                 [BACKUP, NAS2, DISK, NAS])

    def test_words_are_found_in_the_reason_and_never_in_the_path(self) -> None:
        self.assertEqual(_rows(self._get("/events?words=nas")), [HELD])

    def test_a_reason_of_two_lines_is_searched_whole(self) -> None:
        self.assertEqual(_rows(self._get("/events?words=slow+nearly")), [BACKUP])

    # --- decision 3: a switch per status, one each for reached and held back -----
    # (and three by cause, whose rows `tests/test_pruning_pages.py` filters)

    def test_every_switch_is_on_by_default_in_the_records_order(self) -> None:
        body = self._get("/events")
        self.assertEqual([switch["value"] for switch in _inputs(body, "status")],
                         list(STATUSES))
        self.assertEqual(_on(body, "status"), set(STATUSES))
        self.assertEqual([switch["value"] for switch in _inputs(body, "held")],
                         ["no", "yes"])
        self.assertEqual(_on(body, "held"), {"no", "yes"})

    def test_the_status_switches_filter_by_the_status_an_event_moved_to(self) -> None:
        body = self._get("/events?status=error&status=warn")
        self.assertEqual(_rows(body), [BACKUP, HELD, NAS2, DISK, NAS])
        self.assertEqual(_on(body, "status"), {"error", "warn"})
        self.assertEqual(_rows(self._get("/events?status=undefined")), [REMOVED])

    def test_reached_and_held_back(self) -> None:
        for query, shown, on in (
                ("held=no", [ROOT, REMOVED, PIN, NAS2, DISK, NAS], {"no"}),
                ("held=yes", [BACKUP, HELD], {"yes"}),
                ("held=no&held=yes", EVERY, {"no", "yes"})):
            with self.subTest(query=query):
                body = self._get(f"/events?{query}")
                self.assertEqual(_rows(body), shown)
                self.assertEqual(_on(body, "held"), on)

    def test_the_held_back_switches_are_labeled_reached_and_held_back(self) -> None:
        body = self._get("/events")
        for switch, label in zip(_inputs(body, "held"), ("reached", "held back"),
                                 strict=True):
            self.assertRegex(body, rf'<label\b[^>]*for="{re.escape(switch["id"])}"'
                                   rf"[^>]*>\s*{label}\s*</label>")

    def test_maintenance_the_status_is_not_maintenance_the_rule(self) -> None:
        # The failure a pin held back moved to error; turning the status off hides
        # the pin, not what the pin held back.
        body = self._get("/events?status=error&status=warn&status=ok&status=undefined")
        self.assertEqual(_rows(body), [ROOT, BACKUP, REMOVED, HELD, NAS2, DISK, NAS])
        self.assertEqual(_rows(self._get("/events?status=maintenance")), [PIN])

    def test_a_group_with_every_switch_on_filters_nothing(self) -> None:
        body = self._get(f"/events?{ALL_ON}")
        self.assertEqual(_rows(body), EVERY)
        self.assertEqual(_line(body), "8 events")
        self.assertFalse(_has_reset(body))

    def test_a_group_with_every_switch_on_is_written_into_no_link(self) -> None:
        body = self._get(f"/events?{ALL_ON}&under=/hosts&from=now-15m")
        for words, href in _controls(body).items():
            if not href:
                continue
            with self.subTest(control=words):
                query = _query(href)
                self.assertEqual(query.get("under"), ["/hosts"])
                self.assertNotIn("status", query)
                self.assertNotIn("held", query)

    # --- decision 4: the window and its bar are the Series view's ------------------

    def test_an_event_is_in_the_window_when_its_time_is_ends_included(self) -> None:
        self.assertEqual(_rows(self._get("/events?from=now-15m")),
                         [ROOT, BACKUP, REMOVED])
        self.assertEqual(
            _rows(self._get("/events?from=2026-09-26T17:40&to=2026-09-26T17:45")),
            [REMOVED, PIN])

    @skipIf(not hasattr(time, "tzset"), "no tzset on this platform")
    def test_an_event_is_in_the_window_by_its_instant_on_any_machines_clock(
            self) -> None:
        """An event's time is an instant (ADR-0120): the machine's own clock has no
        say in which events a window holds, nor in when a row says one happened.

        **Asserted under a local zone that is neither UTC nor the configured one, on
        purpose**: an instant read through the machine's clock on its way would move
        by that clock's offset there, and by nothing in a container that keeps UTC.
        """
        try:
            with mock.patch.dict(os.environ, {"TZ": "America/New_York"}):
                time.tzset()
                self.assertEqual(_rows(self._get("/events?from=now-15m")),
                                 [ROOT, BACKUP, REMOVED])
                body = self._get("/events?from=2026-09-26T17:40&to=2026-09-26T17:45")
                self.assertEqual(_rows(body), [REMOVED, PIN])
                self.assertIn("2026-09-26 17:45:00", body)
        finally:
            time.tzset()          # back to whatever the real environment says

    def test_the_bar_names_the_window_and_everything_kept_by_the_logs_ends(
            self) -> None:
        self.assertEqual(_range(self._get("/events")),
                         "Everything kept · 2026-09-26 17:00 – 18:00 CEST")
        self.assertEqual(_range(self._get("/events?from=now-15m")),
                         "Last 15 minutes · 2026-09-26 17:45 – 18:00 CEST")

    def test_the_presets_reach_to_the_first_past_the_oldest_event(self) -> None:
        self.assertEqual(_presets(self._get("/events")), ["1h", "all kept"])
        self.clock(360)
        self.assertEqual(_presets(self._get("/events")), ["1h", "6h", "all kept"])

    def test_every_link_the_bar_draws_keeps_the_other_filters(self) -> None:
        controls = _controls(self._get(
            "/events?under=/hosts&words=disk&status=error&status=warn&held=no"
            "&from=now-15m"))
        for words in ("1h", "all kept", "← earlier", "zoom out"):
            with self.subTest(control=words):
                self.assertEqual(urlsplit(controls[words]).path, "/events")
                query = _query(controls[words])
                self.assertEqual(query["under"], ["/hosts"])
                self.assertEqual(query["words"], ["disk"])
                self.assertEqual(query["status"], ["error", "warn"])
                self.assertEqual(query["held"], ["no"])
        self.assertEqual(_query(controls["1h"])["from"], ["now-1h"])
        self.assertNotIn("from", _query(controls["all kept"]))

    def test_earlier_pages_back_half_a_window(self) -> None:
        earlier = _query(_controls(self._get("/events?from=now-20m"))["← earlier"])
        self.assertEqual((earlier["from"], earlier["to"]),
                         (["2026-09-26T15:30:00Z"], ["2026-09-26T15:50:00Z"]))
        self.assertEqual(
            _rows(self._get("/events?from=2026-09-26T15:30:00Z"
                            "&to=2026-09-26T15:50:00Z")),
            [BACKUP, REMOVED, PIN, HELD])

    def test_the_form_keeps_the_window_as_written(self) -> None:
        for query, window in (
                ("from=now-15m&status=error", {"from": "now-15m"}),
                ("from=2026-09-26T17:40&to=2026-09-26T17:45",
                 {"from": "2026-09-26T17:40", "to": "2026-09-26T17:45"}),
                ("status=error", {})):
            with self.subTest(query=query):
                body = self._get(f"/events?{query}")
                kept = {name: field["value"] for name in ("from", "to")
                        for field in _inputs(body, name)
                        if field.get("type") == "hidden"}
                self.assertEqual(kept, window)

    # --- decision 5: a line says how many match; an empty table says which empty ---

    def test_the_line_counts_the_window_and_what_matches(self) -> None:
        for query, said in (("", "8 events"),
                            ("from=now-15m", "3 events"),
                            ("under=/hosts/nas", "3 of 8 events match"),
                            ("under=/hosts/nas&from=now-15m", "1 of 3 events matches")):
            with self.subTest(query=query):
                self.assertEqual(_line(self._get(f"/events?{query}")), said)

    def test_one_event_is_one_event(self) -> None:
        self.tree.restore_events(LOG[:1])
        self.assertEqual(_line(self._get("/events")), "1 event")

    def test_the_counts_are_exact_and_every_match_is_listed(self) -> None:
        self.tree.restore_events(
            _event(minute / 20, f"/load/n{minute}", OK, WARN, [f"reading {minute}"])
            for minute in range(1000))
        body = self._get("/events")
        self.assertEqual(len(_rows(body)), 1000)
        self.assertEqual(_line(body), "1,000 events")
        body = self._get("/events?under=/load/n7")
        self.assertEqual(_rows(body), ["reading 7"])
        self.assertEqual(_line(body), "1 of 1,000 events matches")

    def test_a_window_reaching_past_the_log_says_where_the_log_begins(self) -> None:
        self.assertEqual(_line(self._get("/events?from=now-6h")),
                         "8 events · the log reaches back to 2026-09-26 17:00")
        # A window that starts where the log does reaches past nothing.
        self.assertEqual(_line(self._get("/events?from=now-1h")), "8 events")
        body = self._get("/events?from=2026-09-26T16:00&to=2026-09-26T16:30")
        self.assertEqual(_line(body),
                         "0 events · the log reaches back to 2026-09-26 17:00")
        self.assertIn("No events in this window.", _words(body))

    def test_an_empty_log_says_so(self) -> None:
        self.tree.restore_events(())
        for query in ("", "status=error&from=now-15m"):
            with self.subTest(query=query):
                body = self._get(f"/events?{query}")
                self.assertEqual(_rows(body), [])
                self.assertIn("No events yet.", _words(body))
                self.assertNotIn("in this window", _words(body))

    def test_a_window_the_log_holds_nothing_in_says_so(self) -> None:
        body = self._get("/events?from=2026-09-26T17:01&to=2026-09-26T17:05"
                         "&status=error")
        self.assertEqual(_rows(body), [])
        self.assertIn("No events in this window.", _words(body))
        self.assertNotIn("No events yet.", _words(body))

    def test_filters_that_leave_nothing_say_how_many_there_were(self) -> None:
        for query, said in (
                ("words=zebra", "None of the 8 events in this window match."),
                ("words=zebra&from=now-15m",
                 "None of the 3 events in this window match."),
                ("words=zebra&from=2026-09-26T17:25&to=2026-09-26T17:35",
                 "The only event in this window does not match.")):
            with self.subTest(query=query):
                body = self._get(f"/events?{query}")
                self.assertEqual(_rows(body), [])
                self.assertIn(said, _words(body))

    def test_reset_stands_beside_the_line_whenever_anything_is_set(self) -> None:
        for query, shown in (("", False), (ALL_ON, False), ("under=&words=", False),
                             ("from=now-15m", True), ("under=/hosts", True),
                             ("words=disk", True), ("status=error", True),
                             ("held=yes", True), ("words=zebra", True)):
            with self.subTest(query=query):
                self.assertEqual(_has_reset(self._get(f"/events?{query}")), shown)
