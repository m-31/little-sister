"""A line is a template over its record (ADR-0126): the notation, and what prints.

Each class holds one sentence of the record to account. A template names a record's
field by its dotted name and a word under ``line.``, so that neither can stand for
the other (decision 2); a segment is shown only when the values it names are there,
and a value is absent when it is null, missing, empty or false (decision 3); a link
is Markdown's own, and a target that is absent or no http(s) URL leaves the link's
words as plain text (decision 4); ``{{`` and ``}}`` write a brace, a time under
``at``, ``started`` or ``ended`` is written in the configured zone, and a value
absent outside every segment prints ``—`` (decision 5). What the notation cannot
read is refused, naming the character it stopped at, because a refusal stops the
start and the file it names may hold a long template.
"""
from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any, ClassVar
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from little_sister import line_template, spans
from little_sister.line_template import ABSENT, TemplateError, parse, render
from little_sister.reasons import plain
from little_sister.render import render_markdown


def _said(source: str, record: Mapping[str, Any] | None = None,
          words: Mapping[str, object] | None = None,
          beneath: str | None = None) -> str:
    """``source`` rendered over ``record`` and ``words``, ``beneath`` standing for
    the layer ``{line.default}`` names."""
    return render(parse(source), record or {}, words or {},
                  beneath=None if beneath is None else parse(beneath))


def _hrefs(text: str) -> list[str]:
    """Where the links of ``text`` lead once the page renders it, unescaped."""
    return [html.unescape(href) for href in
            re.findall(r'<a href="([^"]*)"', str(render_markdown(text)))]


def _berlin() -> Any:
    """The configured zone and format, as a deployment's settings set them."""
    return mock.patch("little_sister.config.config",
                      mock.Mock(tzinfo=ZoneInfo("Europe/Berlin"),
                                time_format="%Y-%m-%d %H:%M"))


class NotationTests(TestCase):
    """``{field.path}`` is a record's field by its dotted name, ``{line.word}`` a
    word, ``{line.default}`` the layer beneath, and everything else is Markdown, in
    which a brace means nothing (decision 5)."""

    def test_a_field_is_named_by_its_dotted_name(self) -> None:
        record = {"completed": {"run_number": 41}, "branch": "main"}
        self.assertEqual(_said("#{completed.run_number} on {branch}", record),
                         "#41 on main")

    def test_a_word_is_named_under_line(self) -> None:
        self.assertEqual(_said("{line.why}", words={"why": "it is a day old"}),
                         "it is a day old")

    def test_a_field_never_stands_for_a_word_nor_a_word_for_a_field(self) -> None:
        record = {"why": "the record's", "line": {"why": "a field named line"}}
        self.assertEqual(_said("{why} / {line.why}", record, {"why": "the word"}),
                         "the record's / the word")

    def test_everything_else_is_markdown_and_left_as_it_is_written(self) -> None:
        self.assertEqual(_said("**{name}** — *see* `it` (here)", {"name": "main"}),
                         "**main** — *see* `it` (here)")

    def test_two_braces_write_one(self) -> None:
        self.assertEqual(_said("{{as written}} {{{name}}}", {"name": "main"}),
                         "{as written} {main}")

    def test_with_nothing_beneath_the_layer_beneath_is_not_there(self) -> None:
        self.assertEqual(_said("{line.default} — more"), f"{ABSENT} — more")

    def test_line_default_is_the_layer_beneath_over_the_same_values(self) -> None:
        self.assertEqual(
            _said("{line.default} — page {line.who}", {"name": "main"},
                  {"who": "the on-call"}, beneath="**{name}** failed"),
            "**main** failed — page the on-call")


class AbsentTests(TestCase):
    """A value is absent when it is null, missing, empty or false, and one absent
    outside every segment prints ``—``, the library's spelling of *none*
    (decisions 3 and 5)."""

    ABSENT_VALUES: ClassVar[dict[str, object]] = {
        "null": None, "empty text": "", "an empty list": [], "an empty mapping": {},
        "false": False}

    def test_each_absent_value_prints_the_dash(self) -> None:
        for what, value in self.ABSENT_VALUES.items():
            with self.subTest(what):
                self.assertEqual(_said("run {number}", {"number": value}),
                                 f"run {ABSENT}")

    def test_so_does_a_field_the_record_does_not_hold(self) -> None:
        self.assertEqual(_said("run {number}"), f"run {ABSENT}")
        self.assertEqual(_said("run {completed.number}", {"completed": None}),
                         f"run {ABSENT}")
        self.assertEqual(_said("run {completed.number}", {"completed": "text"}),
                         f"run {ABSENT}")

    def test_and_a_word_the_grading_did_not_hand_over(self) -> None:
        self.assertEqual(_said("in {line.region}"), f"in {ABSENT}")

    def test_zero_is_a_value(self) -> None:
        self.assertEqual(_said("{failed} failed", {"failed": 0}), "0 failed")
        self.assertEqual(_said("{line.failed} failed", words={"failed": 0}),
                         "0 failed")

    def test_the_dash_is_the_one_the_library_writes_for_none(self) -> None:
        self.assertEqual(ABSENT, spans.format_span(None))


class SegmentTests(TestCase):
    """A segment is shown only when the values it names are there. ``{? …}`` names
    the values it prints, ``{?name: …}`` one it does not print as well, so that a
    flag works, and segments nest (decisions 3 and 5)."""

    def test_a_segment_is_shown_when_what_it_prints_is_there(self) -> None:
        self.assertEqual(_said("CI{? on {branch}}", {"branch": "main"}),
                         "CI on main")

    def test_and_left_out_when_it_is_not(self) -> None:
        for what, value in AbsentTests.ABSENT_VALUES.items():
            with self.subTest(what):
                self.assertEqual(_said("CI{? on {branch}}", {"branch": value}), "CI")
        self.assertEqual(_said("CI{? on {branch}}"), "CI")

    def test_every_value_it_prints_must_be_there(self) -> None:
        source = "CI{? on {branch} by {actor}}"
        self.assertEqual(_said(source, {"branch": "main"}), "CI")
        self.assertEqual(_said(source, {"branch": "main", "actor": "ann"}),
                         "CI on main by ann")

    def test_a_flag_names_a_value_it_does_not_print(self) -> None:
        source = "#41{?line.running: · *in progress*}"
        self.assertEqual(_said(source, words={"running": True}),
                         "#41 · *in progress*")
        self.assertEqual(_said(source, words={"running": False}), "#41")
        self.assertEqual(_said(source), "#41")

    def test_a_flag_is_a_field_too_and_a_mapping_is_one(self) -> None:
        source = "passed{?running: · #{running.run_number} running}"
        self.assertEqual(_said(source, {"running": {"run_number": 42}}),
                         "passed · #42 running")
        self.assertEqual(_said(source, {"running": None}), "passed")

    def test_a_flagged_segment_needs_what_it_prints_as_well(self) -> None:
        source = "passed{?running: · #{running.run_number} running}"
        self.assertEqual(_said(source, {"running": {"run_number": None}}), "passed")

    def test_segments_nest(self) -> None:
        source = "CI{? on {branch}{? at {place}}}"
        self.assertEqual(_said(source, {"branch": "main", "place": "home"}),
                         "CI on main at home")
        self.assertEqual(_said(source, {"branch": "main"}), "CI on main")
        self.assertEqual(_said(source, {"place": "home"}), "CI")

    def test_a_segment_holds_back_none_around_it(self) -> None:
        self.assertEqual(_said("{a}{? {b}} {c}", {"a": "x", "c": "z"}), "x z")

    def test_what_follows_the_mark_is_the_segments_own(self) -> None:
        self.assertEqual(_said("a{?{x}}b", {"x": 1}), "a1b")
        self.assertEqual(_said("a{? {x}}b", {"x": 1}), "a 1b")
        self.assertEqual(_said("a{?x: x}b", {"x": 1}), "a xb")

    def test_a_segment_never_prints_the_dash(self) -> None:
        self.assertNotIn(ABSENT, _said("{? {a}}{?b: {c}}", {"b": True}))


class TimeTests(TestCase):
    """A time under ``at``, ``started`` or ``ended`` is written in the configured
    zone and ``time_format``, through ``spans.local_time`` and never a path of its
    own (decisions 1 and 5)."""

    def test_a_timed_field_is_written_in_the_configured_zone(self) -> None:
        record = {"completed": {"started": "2026-10-11T08:00:00Z"}}
        with _berlin():
            self.assertEqual(_said("started {completed.started}", record),
                             "started 2026-10-11 10:00")

    def test_under_each_of_the_three_names_at_any_depth(self) -> None:
        moment = "2026-10-11T08:00:00Z"
        record = {"at": moment,
                  "run": {"started": moment, "updated": {"ended": moment}}}
        with _berlin():
            self.assertEqual(_said("{at} {run.started} {run.updated.ended}", record),
                             "2026-10-11 10:00 2026-10-11 10:00 2026-10-11 10:00")

    def test_through_the_one_function_every_page_time_goes_through(self) -> None:
        self.assertIs(line_template.local_time, spans.local_time)
        with mock.patch.object(line_template, "local_time",
                               return_value="the page's words") as written:
            self.assertEqual(_said("{at}", {"at": "2026-10-11T08:00:00Z"}),
                             "the page's words")
        (moment,), _ = written.call_args
        self.assertEqual(moment.isoformat(), "2026-10-11T08:00:00+00:00")

    def test_a_word_is_written_as_the_grading_handed_it(self) -> None:
        with _berlin():
            self.assertEqual(_said("{line.at}", words={"at": "2026-10-11T08:00:00Z"}),
                             "2026-10-11T08:00:00Z")

    def test_a_time_under_another_name_is_text(self) -> None:
        with _berlin():
            self.assertEqual(_said("{created}", {"created": "2026-10-11T08:00:00Z"}),
                             "2026-10-11T08:00:00Z")

    def test_a_timed_name_that_holds_no_time_is_written_as_held(self) -> None:
        with _berlin():
            self.assertEqual(_said("{at}", {"at": "soon"}), "soon")
            self.assertEqual(_said("{at}", {"at": "2026-10-11T08:00:00"}),
                             "2026-10-11T08:00:00")

    def test_a_timed_name_that_holds_no_text_is_written_as_held(self) -> None:
        with _berlin():
            self.assertEqual(_said("{at}", {"at": 5}), "5")

    def test_a_time_the_configured_zone_cannot_hold_is_written_as_held(self) -> None:
        with _berlin():
            self.assertEqual(_said("{at}", {"at": "9999-12-31T23:30:00Z"}),
                             "9999-12-31T23:30:00Z")

    def test_a_time_that_is_not_there_is_absent(self) -> None:
        self.assertEqual(_said("ended {ended}", {"ended": None}), f"ended {ABSENT}")
        self.assertEqual(_said("run{? ended {ended}}", {"ended": None}), "run")


class EscapingTests(TestCase):
    """The library escapes what it substitutes: a value as text, as ``plain()``
    does (decision 4)."""

    def test_a_value_is_escaped_as_plain_does(self) -> None:
        value = r"*not bold* [not](a link) `nor code` \ https://ci.example.org"
        self.assertEqual(_said("{x}", {"x": value}), plain(value))
        self.assertEqual(_said("{line.x}", words={"x": value}), plain(value))

    def test_so_the_page_shows_it_as_it_reads(self) -> None:
        value = "*a* [b](c) https://ci.example.org"
        shown = str(render_markdown(_said("**{x}**", {"x": value})))
        self.assertIn("<strong>*a* [b](c) https://ci.example.org</strong>", shown)
        self.assertNotIn("<a ", shown)

    def test_a_value_that_is_not_text_is_written_as_its_json(self) -> None:
        self.assertEqual(_said("{a} {b} {c} {d}",
                               {"a": 41, "b": 2.5, "c": True, "d": ["x", "y"]}),
                         plain('41 2.5 true ["x", "y"]'))


class LinkTests(TestCase):
    """A link is Markdown's own, and its target a URL the record holds or a word,
    written as a URL; a target that is absent or no http(s) URL leaves the link's
    words as plain text, so that a missing link never hides what it labels
    (decision 4)."""

    URL = "https://ci.example.org/acme/shop/runs/41"

    def test_a_url_the_record_holds_is_a_target(self) -> None:
        text = _said("[#{n}]({url})", {"n": 41, "url": self.URL})
        self.assertEqual(text, f"[#41]({self.URL})")
        self.assertEqual(_hrefs(text), [self.URL])

    def test_so_is_a_word(self) -> None:
        self.assertEqual(_said("[run]({line.link})", words={"link": self.URL}),
                         f"[run]({self.URL})")

    def test_an_absent_target_leaves_the_words(self) -> None:
        for what, value in AbsentTests.ABSENT_VALUES.items():
            with self.subTest(what):
                self.assertEqual(_said("[#{n}]({url})", {"n": 41, "url": value}),
                                 "#41")
        self.assertEqual(_said("[#{n}]({url})", {"n": 41}), "#41")

    def test_so_does_a_target_that_is_no_http_url(self) -> None:
        for target in ("javascript:alert(1)", "ftp://files.example.org/run",
                       "/acme/shop/runs/41", "mailto:ops@example.org", "https://",
                       "http:ci.example.org", "https://ci.example.org/a b",
                       "https://ci.example.org/a\nb", "http://[::1", 41,
                       ["https://ci.example.org"]):
            with self.subTest(target=target):
                text = _said("[#{n}]({url})", {"n": 41, "url": target})
                self.assertEqual(text, "#41")
                self.assertEqual(_hrefs(text), [])

    def test_the_scheme_is_read_in_either_case(self) -> None:
        url = "HTTPS://ci.example.org/runs/41"
        self.assertEqual(_said("[run]({url})", {"url": url}), f"[run]({url})")

    def test_a_missing_link_never_hides_what_it_labels(self) -> None:
        self.assertEqual(_said("[{name}]({url})", {"name": "shop"}), "shop")
        self.assertEqual(_said("[{name}]({url})"), ABSENT)

    def test_the_words_are_values_and_escaped_as_values(self) -> None:
        text = _said("[{name}]({url})", {"name": "a]b*c", "url": self.URL})
        self.assertEqual(text, f"[{plain('a]b*c')}]({self.URL})")
        self.assertEqual(_hrefs(text), [self.URL])

    def test_balanced_parentheses_are_written_as_they_are(self) -> None:
        url = ("https://issues.example.org/issues#~(filters~(severity~(equals~"
               "(~'HIGH)))~issue~'i-1)")
        text = _said("[control]({line.link})", words={"link": url})
        self.assertEqual(text, f"[control]({url})")
        self.assertEqual(_hrefs(text), [url])

    def test_what_a_target_cannot_hold_is_escaped(self) -> None:
        for url, written in (
                ("https://ci.example.org/a)b", r"https://ci.example.org/a\)b"),
                ("https://ci.example.org/a(b", r"https://ci.example.org/a\(b"),
                ("https://ci.example.org/(a))(b", r"https://ci.example.org/(a)\)\(b"),
                ("https://ci.example.org/a\\(b)", r"https://ci.example.org/a\\(b)"),
                ("https://ci.example.org/?a=1&copy;b",
                 r"https://ci.example.org/?a=1\&copy;b"),
                ("https://ci.example.org/?a=1&b=2", "https://ci.example.org/?a=1&b=2")):
            with self.subTest(url=url):
                text = _said("[run]({url})", {"url": url})
                self.assertEqual(text, f"[run]({written})")
                self.assertEqual(len(_hrefs(text)), 1)

    def test_and_the_page_leads_where_the_value_said(self) -> None:
        for url in ("https://ci.example.org/a)b", "https://ci.example.org/(a))(b",
                    "https://ci.example.org/?a=1&copy;b"):
            with self.subTest(url=url):
                self.assertEqual(_hrefs(_said("[run]({url})", {"url": url})), [url])

    def test_parentheses_nested_past_what_markdown_reads_are_escaped(self) -> None:
        url = "https://ci.example.org/" + "(" * 33 + "a" + ")" * 33
        text = _said("[run]({url})", {"url": url})
        self.assertEqual(text, "[run](https://ci.example.org/" + "\\(" * 33 + "a"
                         + "\\)" * 33 + ")")
        self.assertEqual(_hrefs(text), [url])
        shallow = "https://ci.example.org/" + "(" * 32 + "a" + ")" * 32
        self.assertEqual(_said("[run]({url})", {"url": shallow}), f"[run]({shallow})")

    def test_a_target_holds_back_no_segment(self) -> None:
        source = "shop{? · [{name}]({url})}"
        self.assertEqual(_said(source, {"name": "run"}), "shop · run")
        self.assertEqual(_said(source, {"url": self.URL}), "shop")

    def test_a_link_written_out_is_left_as_written(self) -> None:
        source = "{name} — [runbook](https://wiki.example.org/runbooks/shop)"
        self.assertEqual(_said(source, {"name": "shop"}),
                         "shop — [runbook](https://wiki.example.org/runbooks/shop)")

    def test_a_line_may_carry_two_links(self) -> None:
        text = _said("[{name}]({completed.url}): passed · [running]({running.url})",
                     {"name": "shop", "completed": {"url": self.URL},
                      "running": {"url": self.URL + "2"}})
        self.assertEqual(_hrefs(text), [self.URL, self.URL + "2"])

    def test_brackets_that_make_no_link_are_text(self) -> None:
        self.assertEqual(_said("[{a}] and [b]", {"a": "x"}), "[x] and [b]")


class RefusedTests(TestCase):
    """What the notation cannot read is refused, naming the character it stopped
    at (decision 5)."""

    def _refused(self, source: str) -> str:
        with self.assertRaises(TemplateError) as caught:
            parse(source)
        return str(caught.exception)

    def test_a_brace_that_opens_nothing(self) -> None:
        for source in ("{ branch}", "{}", "{a b}", "{a..b}", "{.a}", "{a.}",
                       "x {branch", "{line}", "{line.}", "{line.a.b}"):
            with self.subTest(source=source):
                message = self._refused(source)
                self.assertIn(f"character {source.index('{') + 1}", message)
                self.assertIn("{{", message)

    def test_a_brace_that_closes_nothing(self) -> None:
        self.assertIn("character 3", self._refused("a } b"))
        self.assertIn("character 4", self._refused("{x}} b"))

    def test_a_refusal_inside_a_links_words_names_its_own_character(self) -> None:
        self.assertIn("character 4", self._refused("[a } b]({url})"))
        self.assertIn("character 2", self._refused("[{ x}]({url})"))

    def test_a_segment_that_never_ends(self) -> None:
        self.assertIn("character 3", self._refused("CI{? on {branch}"))
        self.assertIn("character 1", self._refused("{?a: {? {b}}"))

    def test_the_layer_beneath_is_no_flag(self) -> None:
        self.assertIn("line.default", self._refused("{?line.default: more}"))

    def test_a_target_is_one_value(self) -> None:
        for source in ("[x](https://issues.example.org/{line.id})",
                       '[x]({url} "a title")', "[x]( {url} )", "[x]({url}{id})",
                       "[x]({line.default})"):
            with self.subTest(source=source):
                self.assertIn("character 4", self._refused(source))


class NamesTests(TestCase):
    """A template says which fields and words it names, wherever it names them —
    what startup checks against what the type declares (decision 5)."""

    def test_it_says_its_fields_and_its_words(self) -> None:
        template = parse("[{a.b}]({url}){?flag: {line.why}}{? {line.region}"
                         "{?line.flag: {c}}} {line.default}")
        self.assertEqual(template.fields, {"a.b", "url", "flag", "c"})
        self.assertEqual(template.words, {"why", "region", "flag"})
        self.assertTrue(template.defers)

    def test_a_template_without_the_layer_beneath_does_not_defer(self) -> None:
        self.assertFalse(parse("{a} {{line.default}}").defers)

    def test_it_keeps_the_text_it_was_read_from(self) -> None:
        self.assertEqual(parse("**{name}**").source, "**{name}**")
