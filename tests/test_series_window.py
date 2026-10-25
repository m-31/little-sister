"""A Series view is drawn over the window its URL names (ADR-0098), read against the
record's sentences.

The estate is one host with two checks on its node: its metrics, read every minute for
an hour from 17:00 in the configured zone, a load that counts the minutes, a rate
that stands on a node beneath and a late figure its records carry only from the
fiftieth minute on; and a second check whose temperature was read only in the hour's
first ten minutes. The page's clock is set where each test says.
"""
from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import NamedTuple
from unittest import TestCase, mock
from urllib.parse import parse_qs, urlsplit

from little_sister import app as app_module
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)          # 17:00 in Berlin
HOST = "/lab/host"


class _Kept(Check):
    """A check whose readings the test writes into the store the engine reads."""

    type_name = "kept"

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class _Beside(_Kept):
    type_name = "beside"


def _query(href: str) -> tuple[str, dict[str, str]]:
    """A link's path and its query, one value a key."""
    parts = urlsplit(html.unescape(href))
    return parts.path, {key: values[0] for key, values in parse_qs(parts.query).items()}


def _z(minutes: float) -> str:
    """The instant ``minutes`` after 17:00, as a link the page makes writes it."""
    moment = T0 + timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Control(NamedTuple):
    """One control of the window's bar: where it leads, whether it is the window the
    page is drawn over, and whether it is shown disabled, leading nowhere."""

    path: str
    query: dict[str, str]
    current: bool
    disabled: bool


class _Bar(NamedTuple):
    """The window's bar: the window as it names it, and its two groups of controls."""

    range: str
    presets: dict[str, _Control]
    moves: dict[str, _Control]


def estate() -> tuple[StatusTree, Engine]:
    """The estate the module's docstring describes: its tree, and an engine whose store
    keeps the hour of readings."""
    tree = StatusTree()
    metrics = _Kept(path=HOST, series_keep=500, frequency_seconds=60, measures={
        "load": "", "rate": {"unit": "%", "node": "rate"}, "late": ""})
    beside = _Beside(path=HOST, series_keep=500, frequency_seconds=60,
                     measures={"temp": "°C"})
    store = MemoryStore()
    for minute in range(60):
        at = T0 + timedelta(minutes=minute)
        read = {"load": minute, "rate": 50} | ({"late": minute} if minute >= 50
                                                else {})
        store.add(SeriesKey("kept", HOST, "alpha"),
                  SeriesRecord(read, at, code=StatusCode.OK), keep=500)
        if minute < 10:
            store.add(SeriesKey("beside", HOST, "alpha"),
                      SeriesRecord({"temp": 40}, at, code=StatusCode.OK), keep=500)
    for path in ("/lab", HOST, f"{HOST}/rate"):
        tree.upsert(path, StatusCode.OK, frequency_seconds=60)
    return tree, Engine([metrics, beside], tree, series=store)


#: The configuration the estate is read in: Berlin's clock, written to the second.
SETTINGS = {"timezone": "Europe/Berlin", "time_format": "%Y-%m-%d %H:%M:%S"}


class WindowTests(TestCase):
    """The window, how it is written, what it reaches, and how it is moved."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.tree, app_module.engine = estate()
        app_module.status_tree = self.tree
        settings = mock.patch("little_sister.config.config",
                              replace(app_module.config, **SETTINGS))
        settings.start()
        self.addCleanup(settings.stop)
        self.clock(60)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

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

    @staticmethod
    def _curves(body: str) -> dict[str, dict[str, str]]:
        """Each curve on the page by its title: the ends its accessible name gives,
        its summary, and how many readings it says it was drawn over."""
        found = {}
        for figure in re.findall(r'<figure class="ls-curve">.*?</figure>', body, re.S):
            title = re.search(r'<span class="ls-curve__title">(.*?)</span>', figure)
            summary = re.search(r'<span class="ls-curve__summary">(.*?)</span>\s*'
                                r'</figcaption>', figure, re.S)
            name = re.search(r'aria-label="[^"]*, (\d+) readings? from ([^"]*) to '
                             r'([^"]*)"', figure)
            assert title is not None
            found[title.group(1)] = {
                "summary": re.sub(r"<[^>]+>", "", summary.group(1)) if summary else "",
                "readings": name.group(1) if name else "0",
                "from": name.group(2) if name else "", "to": name.group(3) if name
                else ""}
        return found

    @staticmethod
    def _links(body: str, pattern: str) -> list[str]:
        return re.findall(pattern, body)

    # --- decision 1: the window is written as `from` and `to` ---------------------

    def test_two_instants_in_the_configured_zone(self) -> None:
        load = self._curves(self._get(
            f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20"))["load"]
        self.assertEqual((load["from"], load["to"]),
                         ("2026-09-26 17:10:00", "2026-09-26 17:20:00"))

    def test_an_instant_with_its_offset_or_a_z(self) -> None:
        load = self._curves(self._get(
            f"/series{HOST}?from=2026-09-26T15:10:00Z"
            "&to=2026-09-26T17:20:00%2B02:00"))["load"]
        self.assertEqual((load["from"], load["to"]),
                         ("2026-09-26 17:10:00", "2026-09-26 17:20:00"))

    def test_now_and_a_duration_back_from_it(self) -> None:
        load = self._curves(self._get(f"/series{HOST}?from=now-30m&to=now"))["load"]
        self.assertEqual((load["from"], load["to"]),
                         ("2026-09-26 17:30:00", "2026-09-26 18:00:00"))

    def test_to_is_now_where_it_is_left_out(self) -> None:
        load = self._curves(self._get(f"/series{HOST}?from=2026-09-26T17:50"))["load"]
        self.assertEqual(load["to"], "2026-09-26 18:00:00")

    def test_without_from_everything_kept(self) -> None:
        for url, to in ((f"/series{HOST}", "2026-09-26 17:59:00"),
                        (f"/series{HOST}?to=2026-09-26T17:30", "2026-09-26 17:30:00")):
            with self.subTest(url=url):
                load = self._curves(self._get(url))["load"]
                self.assertEqual((load["from"], load["to"]),
                                 ("2026-09-26 17:00:00", to))

    def test_what_the_server_cannot_read_is_refused_naming_the_parameter(self) -> None:
        for query, named in (("from=yesterday", "from"), ("to=now-6M", "to"),
                             ("from=now-", "from"), ("from=now%2B1h", "from"),
                             ("from=now&to=now-1h", "from"),
                             ("from=now-0m", "from")):
            with self.subTest(query=query):
                body = self._get(f"/series{HOST}?{query}", status=400)
                self.assertIn(f"<code>{named}</code>", body)

    # --- decision 2: the window is the Series view's ------------------------------

    def test_every_curve_is_drawn_over_the_window_alone(self) -> None:
        load = self._curves(self._get(
            f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20"))["load"]
        self.assertEqual(load["readings"], "11")
        self.assertIn("newest 20 · lowest 10 · highest 20", load["summary"])

    def test_a_curve_with_nothing_in_the_window_keeps_its_place_and_says_so(
            self) -> None:
        curves = self._curves(self._get(
            f"/series{HOST}?from=2026-09-26T17:30&to=2026-09-26T17:40"))
        self.assertEqual(list(curves), list(self._curves(self._get(f"/series{HOST}"))))
        self.assertEqual(curves["temp"]["summary"], "no readings in this window")

    def test_the_axis_is_the_window_as_written(self) -> None:
        load = self._curves(self._get(f"/series{HOST}?from=now-2h"))["load"]
        self.assertEqual((load["from"], load["to"]),
                         ("2026-09-26 16:00:00", "2026-09-26 18:00:00"))

    def test_a_curve_whose_readings_carry_no_value_in_the_window_says_so(self) -> None:
        window = self._curves(self._get(
            f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20"))["late"]
        self.assertEqual((window["readings"], window["summary"]),
                         ("11", "no values in this window"))
        # over everything kept, the same curve has its values
        self.assertIn("newest 59 · lowest 50 · highest 59",
                      self._curves(self._get(f"/series{HOST}"))["late"]["summary"])

    def test_the_bar_and_the_tables_follow_the_window(self) -> None:
        body = self._get(f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20")
        self.assertEqual(self._bar(body).range, "2026-09-26 17:10 – 17:20 CEST")
        rows = re.findall(r'<td class="ls-readings__time"><time datetime="[^"]*">'
                          r'([^<]*)</time>', body)
        kept = sorted(set(rows))
        self.assertTrue(kept)
        self.assertEqual(max(kept), "2026-09-26 17:20:00")
        self.assertGreaterEqual(min(kept), "2026-09-26 17:10:00")

    def test_the_series_crumbs_carry_it_and_the_tabs_do_not(self) -> None:
        body = self._get(f"/series{HOST}?from=now-30m")
        trail = re.search(r'<span class="ls-crumbs">(.*?)</span>\s*'
                          r'(?:<span class="node-title|</h1>)', body, re.S)
        assert trail is not None
        crumbs = [_query(href) for href in
                  re.findall(r'href="([^"]*)" class="[^"]*crumb', trail.group(1))]
        self.assertIn(("/series/lab", {"from": "now-30m"}), crumbs)
        self.assertIn(("/series", {}), crumbs)
        tabs = [_query(href) for href in
                re.findall(r'<a class="ls-views__tab[^"]*" href="([^"]*)"', body)]
        self.assertEqual(tabs, [(f"/status{HOST}", {}), (f"/series{HOST}", {}),
                                (f"/history{HOST}", {}), (f"/notes{HOST}", {}),
                                (f"/copy{HOST}", {})])

    def test_the_index_and_a_node_s_page_take_none(self) -> None:
        # the page is the same but for its own address, which the menu posts back to
        self.assertEqual(self._get("/series?from=now-10m").replace("?from=now-10m", ""),
                         self._get("/series"))
        load = self._curves(self._get(f"/status{HOST}?from=now-10m"))["load"]
        self.assertEqual((load["from"], load["to"]),
                         ("2026-09-26 17:00:00", "2026-09-26 17:59:00"))

    # --- decision 3: one bar names the window and moves it ------------------------

    @staticmethod
    def _bar(body: str) -> _Bar:
        """The window's bar: the window as it names it, read as text, and each of its
        two groups of controls by their words."""
        nav = re.search(r'<nav class="ls-window"[^>]*>(.*?)</nav>', body, re.S)
        assert nav is not None, "no window bar"
        said = re.search(r'<p class="ls-window__range">(.*?)</p>', nav.group(1), re.S)
        assert said is not None, "the bar names no window"
        groups = []
        for name in ("Presets", "Moves"):
            group = re.search(r'<div class="ls-window__group" role="group" '
                              rf'aria-label="{name}">(.*?)</div>', nav.group(1), re.S)
            assert group is not None, f"no {name} group"
            controls = {}
            for attrs, words in re.findall(r'<a ([^>]*)>([^<]*)</a>', group.group(1)):
                href = re.search(r'href="([^"]*)"', attrs)
                path, query = _query(href.group(1)) if href else ("", {})
                controls[html.unescape(words).strip()] = _Control(
                    path, query, "aria-current" in attrs,
                    href is None and 'aria-disabled="true"' in attrs)
            groups.append(controls)
        text = html.unescape(re.sub(r"<[^>]+>", "", said.group(1)))
        return _Bar(" ".join(text.split()), *groups)

    def _css_rule(self, selector: str) -> str:
        """The declarations of the stylesheet's rule for exactly ``selector``."""
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        rule = re.search(rf"(?:^|[}}/])\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
        assert rule is not None, f"no rule for {selector}"
        return rule.group(1)

    def test_the_bar_names_a_window_back_from_now_to_the_minute_with_its_zone(
            self) -> None:
        self.clock(60.5)                     # 18:00:30 in Berlin, on summer time
        self.assertEqual(self._bar(self._get(f"/series{HOST}?from=now-1h")).range,
                         "Last 1 hour · 2026-09-26 17:00 – 18:00 CEST")
        # a window written from now that ends before it is named by its ends
        self.assertEqual(
            self._bar(self._get(f"/series{HOST}?from=now-2h&to=now-1h")).range,
            "2026-09-26 16:00 – 17:00 CEST")

    def test_the_bar_names_two_instants_by_their_ends(self) -> None:
        for query, said in (
                ("from=2026-09-26T17:10&to=2026-09-26T17:20",
                 "2026-09-26 17:10 – 17:20 CEST"),
                ("from=2026-09-25T18:00&to=2026-09-26T18:00",
                 "2026-09-25 18:00 – 2026-09-26 18:00 CEST"),
                # the clocks go back an hour in the night to 2026-10-25
                ("from=2026-10-24T12:00&to=2026-10-26T12:00",
                 "2026-10-24 12:00 CEST – 2026-10-26 12:00 CET")):
            with self.subTest(query=query):
                self.assertEqual(self._bar(self._get(f"/series{HOST}?{query}")).range,
                                 said)

    def test_the_bar_names_everything_kept(self) -> None:
        self.assertEqual(self._bar(self._get(f"/series{HOST}")).range,
                         "Everything kept · 2026-09-26 17:00 – 17:59 CEST")

    def test_the_bar_stays_in_view_while_the_page_scrolls(self) -> None:
        rule = self._css_rule(".ls-window")
        self.assertIn("position: sticky;", rule)
        self.assertIn("top: var(--ls-bar-height);", rule)

    def test_presets_up_to_the_first_reaching_past_what_is_kept(self) -> None:
        self.clock(7 * 60)            # the oldest reading is seven hours old
        presets = self._bar(self._get(f"/series{HOST}")).presets
        self.assertEqual(list(presets), ["1h", "6h", "12h", "all kept"])
        self.assertEqual(presets["6h"][:2], (f"/series{HOST}", {"from": "now-6h"}))
        self.assertEqual(presets["all kept"][:2], (f"/series{HOST}", {}))

    def test_the_preset_of_the_window_s_length_is_marked(self) -> None:
        for query, marked in (("from=now-1h", ["1h"]), ("from=now-60m&to=now", ["1h"]),
                              ("", ["all kept"]), ("from=now-45m", []),
                              ("from=now-2h&to=now-1h", []),
                              # two instants hold still, whatever they span
                              ("from=2026-09-26T17:00&to=2026-09-26T18:00", [])):
            with self.subTest(query=query):
                presets = self._bar(self._get(f"/series{HOST}?{query}")).presets
                self.assertEqual([words for words, control in presets.items()
                                  if control.current], marked)

    def test_the_moves_keep_their_places(self) -> None:
        for query in ("", "from=now-30m", "from=2026-09-26T17:10&to=2026-09-26T17:20"):
            with self.subTest(query=query):
                moves = self._bar(self._get(f"/series{HOST}?{query}")).moves
                self.assertEqual(list(moves),
                                 ["← earlier", "zoom out", "later →", "now"])

    def test_a_move_that_does_not_apply_is_disabled(self) -> None:
        # the clock reads 18:00; the readings run from 17:00 to 17:59
        every = ["← earlier", "zoom out", "later →", "now"]
        for query, disabled in (
                ("", every),                                     # everything kept
                ("from=now-30m", ["later →", "now"]),            # ends now
                ("from=now-2h", every),              # holds every reading, ends now
                ("from=2026-09-26T17:00&to=2026-09-26T17:20", ["← earlier"]),
                ("from=2026-09-26T16:30&to=2026-09-26T17:59",
                 ["← earlier", "zoom out"]),
                ("from=2026-09-26T17:50&to=2026-09-26T18:10", ["later →", "now"]),
                ("from=2026-09-26T17:10&to=2026-09-26T17:20", [])):
            with self.subTest(query=query):
                moves = self._bar(self._get(f"/series{HOST}?{query}")).moves
                self.assertEqual([words for words, control in moves.items()
                                  if control.disabled], disabled)
                self.assertTrue(all(control.path for control in moves.values()
                                    if not control.disabled))

    def test_earlier_zoom_out_later_and_now(self) -> None:
        moves = self._bar(self._get(
            f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20")).moves
        self.assertEqual(moves["← earlier"][:2],
                         (f"/series{HOST}", {"from": _z(5), "to": _z(15)}))
        self.assertEqual(moves["zoom out"][:2],
                         (f"/series{HOST}", {"from": _z(5), "to": _z(25)}))
        self.assertEqual(moves["later →"][:2],
                         (f"/series{HOST}", {"from": _z(15), "to": _z(25)}))
        self.assertEqual(moves["now"][:2], (f"/series{HOST}", {"from": "now-10m"}))

    def test_a_window_that_ends_now_stays_live(self) -> None:
        moves = self._bar(self._get(f"/series{HOST}?from=now-30m")).moves
        # a zoom out that reaches now is the last hour, and moving earlier holds still
        self.assertEqual(moves["zoom out"][:2], (f"/series{HOST}", {"from": "now-1h"}))
        self.assertEqual(moves["← earlier"][:2],
                         (f"/series{HOST}", {"from": _z(15), "to": _z(45)}))
        # a later that reaches now is live too, its length kept
        moves = self._bar(self._get(
            f"/series{HOST}?from=2026-09-26T17:40&to=2026-09-26T17:55")).moves
        self.assertEqual(moves["later →"][:2], (f"/series{HOST}", {"from": "now-15m"}))

    def test_a_live_length_is_written_to_the_minute(self) -> None:
        moves = self._bar(self._get(
            f"/series{HOST}?from=2026-09-26T17:10:00&to=2026-09-26T17:20:20")).moves
        self.assertEqual(moves["now"][:2], (f"/series{HOST}", {"from": "now-10m"}))

    def test_the_page_reads_its_clock_once(self) -> None:
        # a clock that moves while the page is drawn: the window's `now` and the
        # controls' are one reading of it, or a window ending now would offer later
        moments = (T0 + timedelta(minutes=60, seconds=tick) for tick in range(1000))
        with mock.patch.object(app_module, "_now", side_effect=lambda: next(moments)):
            moves = self._bar(self._get(f"/series{HOST}?from=now-30m")).moves
        self.assertTrue(moves["later →"].disabled)
        self.assertTrue(moves["now"].disabled)

    def _stretches(self, body: str) -> list[tuple[str, list[str]]]:
        """Each curve's stretch links, beside the id of the group it stands in."""
        found = []
        for anchor, section in re.findall(
                r'<section class="[^"]*\bls-series-group\b[^"]*" id="([^"]*)">'
                r'(.*?)</section>', body, re.S):
            for figure in re.findall(r'<figure class="ls-curve">.*?</figure>', section,
                                     re.S):
                found.append((anchor, re.findall(
                    r'<a class="ls-curve__stretch" href="([^"]*)"', figure)))
        return found

    def test_every_stretch_of_a_time_axis_leads_into_it_and_back_to_its_curve(
            self) -> None:
        # an hour is labeled every quarter: four stretches, on every curve
        stretches = self._stretches(self._get(f"/series{HOST}?from=now-1h"))
        self.assertEqual({anchor for anchor, _hrefs in stretches}, {"node", "rate"})
        for anchor, hrefs in stretches:
            with self.subTest(anchor=anchor):
                self.assertEqual([_query(href) for href in hrefs], [
                    (f"/series{HOST}", {"from": _z(start), "to": _z(start + 15)})
                    for start in (0, 15, 30, 45)])
                self.assertEqual({urlsplit(html.unescape(href)).fragment
                                  for href in hrefs}, {anchor})

    def test_a_stretch_chosen_at_the_newest_end_holds_still(self) -> None:
        body = self._get(f"/series{HOST}?from=now-1h")
        (_anchor, hrefs), *_rest = self._stretches(body)
        self.assertEqual(_query(hrefs[-1]),
                         (f"/series{HOST}", {"from": _z(45), "to": _z(60)}))

    def test_the_axis_is_a_track_divided_at_its_labels(self) -> None:
        body = self._get(f"/series{HOST}?from=now-1h")
        axis = re.search(r'<svg class="ls-curve__axis"[^>]*>(.*?)</svg>', body, re.S)
        assert axis is not None
        segments = []
        for stretch in re.findall(r'<a class="ls-curve__stretch".*?</a>', axis.group(1),
                                  re.S):
            segment = re.search(r'<rect class="ls-curve__segment" x="([\d.]+)" '
                                r'y="[\d.]+" width="([\d.]+)"', stretch)
            assert segment is not None, "a stretch without its segment of the track"
            segments.append((float(segment.group(1)), float(segment.group(2))))
        labels = [float(x) for x in re.findall(
            r'<text class="ls-curve__time" x="([\d.]+)"', axis.group(1))]
        # the track parts where the labels stand, and nowhere else
        parts = [(left + width + right) / 2 for (left, width), (right, _w)
                 in pairwise(segments)]
        self.assertEqual([round(x) for x in parts], [round(x) for x in labels])

    def test_the_pointer_over_a_stretch_is_a_zoom(self) -> None:
        self.assertIn("cursor: zoom-in;", self._css_rule(".ls-curve__stretch"))

    def test_the_stretches_are_in_the_tab_order_once(self) -> None:
        body = self._get(f"/series{HOST}?from=now-1h")
        axes = re.findall(r'(<svg class="ls-curve__axis"[^>]*>)(.*?)</svg>', body, re.S)
        self.assertGreater(len(axes), 1)
        (opening, inside), *rest = axes
        self.assertNotIn("aria-hidden", opening)
        self.assertNotIn('tabindex="-1"', inside)
        for opening, inside in rest:
            links = re.findall(r'<a class="ls-curve__stretch"[^>]*>', inside)
            self.assertTrue(links)
            self.assertIn('aria-hidden="true"', opening)
            self.assertTrue(all('tabindex="-1"' in link for link in links))

    def test_nothing_follows_the_pointer_across_a_plot(self) -> None:
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        self.assertIsNone(re.search(r"\.ls-curve__hover[^{}]*:hover", css))
        # the strips are still there, each titled with what the pointer finds
        body = self._get(f"/series{HOST}?from=now-1h")
        self.assertRegex(body, r'<g class="ls-curve__hover">\s*<rect [^>]*><title>')

    # --- decision 6: a drag chooses a stretch, one line reads every curve ----------

    def test_the_view_carries_its_script_and_what_the_script_reads(self) -> None:
        body = self._get(f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20")
        self.assertRegex(
            body, r'<script src="/static/js/series\.js\?v=[0-9a-f]{8}"></script>')
        # the window's two instants and the zone they are written in ...
        self.assertRegex(body, r'<div class="ls-series-grid" '
                               r'data-start="2026-09-26T15:10:00Z" '
                               r'data-end="2026-09-26T15:20:00Z" '
                               r'data-zone="Europe/Berlin">')
        # ... and where on each plot they stand, and how tall its strips run
        plots = re.findall(r'<svg class="ls-curve__plot"[^>]*>', body)
        self.assertTrue(plots)
        for plot in plots:
            self.assertIn('data-left="72.0" data-right="744.0" data-top="16.0" '
                          'data-bottom="', plot)

    def test_a_node_s_page_carries_no_script(self) -> None:
        body = self._get(f"/status{HOST}")
        self.assertIn('<figure class="ls-curve"', body)
        self.assertNotIn("series.js", body)
        self.assertNotIn("data-left=", body)

    def test_nothing_on_a_drawing_is_selected_or_picked_up(self) -> None:
        drawings = self._css_rule(".ls-curve__plot,\n.ls-curve__axis")
        self.assertIn("user-select: none;", drawings)
        self.assertIn("-webkit-user-select: none;", drawings)
        self.assertIn("-webkit-user-drag: none;", self._css_rule(".ls-curve__stretch"))

    def test_the_line_s_reading_lies_over_a_summary_on_one_line(self) -> None:
        # out of the caption's flow, so that no caption changes its height while the
        # line moves; where it begins is the script's to write
        self.assertIn("position: relative;", self._css_rule(
            ".ls-series-grid.is-enhanced .ls-curve__head"))
        reading = self._css_rule(".ls-curve__reading")
        for declaration in ("position: absolute;", "right: 0;", "overflow: hidden;",
                            "white-space: nowrap;", "text-overflow: ellipsis;"):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, reading)

    def test_a_node_s_page_has_no_way_in(self) -> None:
        body = self._get(f"/status{HOST}")
        self.assertIn('<figure class="ls-curve"', body)
        self.assertNotIn("ls-curve__stretch", body)
        self.assertNotIn('class="ls-window"', body)
