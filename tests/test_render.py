"""Markdown rendering and the reason-assembly helpers (ADR-0018)."""
import re
from pathlib import Path
from unittest import TestCase

from pytest import mark

from little_sister.checks import code, plain
from little_sister.codes import StatusCode
from little_sister.render import (
    anchor,
    anchors_of,
    first_block,
    names_a_status,
    render_markdown,
    render_markdown_inline,
    short_links,
    sign,
    write_out,
)
from tests.page_tree import parse


class RenderInlineTests(TestCase):
    def test_emphasis_code_and_link_render(self):
        out = str(render_markdown_inline("**b** `c` [x](https://e.com)"))
        self.assertIn("<strong>b</strong>", out)
        self.assertIn("<code>c</code>", out)
        self.assertIn('href="https://e.com"', out)

    def test_inline_has_no_paragraph_wrapper(self):
        self.assertNotIn("<p>", str(render_markdown_inline("hello")))

    def test_links_open_in_new_tab_with_noopener(self):
        out = str(render_markdown_inline("[x](https://e.com)"))
        self.assertIn('target="_blank"', out)
        self.assertIn('rel="noopener noreferrer"', out)

    def test_bare_http_urls_are_linked_and_trim_trailing_punctuation(self):
        out = str(render_markdown_inline(
            "See https://heise.de/a?q=1 and (http://example.com/path)."))
        self.assertIn('href="https://heise.de/a?q=1"', out)
        self.assertIn('>https://heise.de/a?q=1</a>', out)
        self.assertIn('href="http://example.com/path"', out)
        self.assertIn('</a>).', out)
        self.assertEqual(out.count('target="_blank"'), 2)
        self.assertEqual(out.count('rel="noopener noreferrer"'), 2)

    def test_linkification_is_limited_to_explicit_http_urls(self):
        out = str(render_markdown_inline(
            "example.com person@example.com ftp://example.com //example.com"))
        self.assertNotIn("<a", out)

    def test_linkification_skips_code_and_existing_markdown_links(self):
        out = str(render_markdown_inline(
            "`https://code.example` [heise](https://heise.de)"))
        self.assertIn("<code>https://code.example</code>", out)
        self.assertEqual(out.count("<a "), 1)
        self.assertIn(">heise</a>", out)


class RenderSafetyTests(TestCase):
    def test_raw_html_is_escaped(self):
        out = str(render_markdown_inline("<script>alert(1)</script>"))
        self.assertNotIn("<script>", out)
        self.assertIn("&lt;script&gt;", out)

    def test_javascript_link_is_dropped(self):
        out = str(render_markdown_inline("[x](javascript:alert(1))"))
        self.assertNotIn("<a", out)

    @mark.skip(reason="We currently allow images")
    def test_images_are_disabled(self):
        # the image rule is off, so no <img> regardless of the URL scheme
        for src in ("http://e/x.png", "data:image/png;base64,AAAA"):
            self.assertNotIn("<img", str(render_markdown(f"![a]({src})")))


class RenderBlockTests(TestCase):
    def test_block_renders_paragraph_and_list(self):
        out = str(render_markdown("para\n\n- one\n- two"))
        self.assertIn("<p>para</p>", out)
        self.assertIn("<li>one</li>", out)


class FirstBlockTests(TestCase):
    """What the inspection card says of an `about` (ADR-0019 decision 1): its first
    top-level block, rendered as the whole would be, and how many follow."""

    def test_a_paragraph_and_how_many_blocks_follow_it(self):
        self.assertEqual(first_block("First **one**.\n\nSecond.\n\n- a\n- b"),
                         ("<p>First <strong>one</strong>.</p>\n", 2))

    def test_a_paragraph_of_several_lines_is_one_block(self):
        self.assertEqual(first_block("line one\nline two"),
                         ("<p>line one\nline two</p>\n", 0))

    def test_a_list_is_one_block_with_its_items(self):
        self.assertEqual(
            first_block("- a\n\n- b\n\nAfter."),
            ("<ul>\n<li>\n<p>a</p>\n</li>\n<li>\n<p>b</p>\n</li>\n</ul>\n", 1))

    def test_a_code_block_keeps_its_blank_lines(self):
        self.assertEqual(first_block("```\nx = 1\n\ny = 2\n```\n\nText."),
                         ("<pre><code>x = 1\n\ny = 2\n</code></pre>\n", 1))

    def test_a_link_reference_defined_further_down_still_resolves(self):
        block, more = first_block("See [the runbook][rb].\n\nMore.\n\n"
                                  "[rb]: https://example.org/rb")
        self.assertIn('<a href="https://example.org/rb" target="_blank" '
                      'rel="noopener noreferrer">the runbook</a>', block)
        self.assertEqual(more, 1)

    def test_it_is_as_safe_as_the_whole(self):
        block, _ = first_block("<script>x</script> [a](javascript:alert(1))")
        self.assertNotIn("<script>", block)
        self.assertNotIn("<a ", block)          # the scheme is refused, the text stays

    def test_text_with_no_block_is_nothing(self):
        for text in ("", "   ", "\n\n", "[rb]: https://example.org/rb"):
            with self.subTest(text=text):
                self.assertEqual(first_block(text), ("", 0))

    def test_its_signs_are_drawn_in_the_block_too(self):
        block, more = first_block("{error}: restart it.\n\nMore.")
        self.assertIn(sign(StatusCode.ERROR), block)
        self.assertEqual(more, 1)

    def test_a_table_is_one_block(self):
        block, more = first_block("| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter.")
        self.assertTrue(block.startswith("<table>"), block)
        self.assertEqual(more, 1)


class AnchorTests(TestCase):
    """A handbook's headings are anchored as GitHub anchors them (ADR-0133 decision
    3), on its page alone: a link GitHub would follow into a section follows into it
    there, and one to a section of the page stays in it."""

    def test_the_words_as_github_anchors_them(self):
        for words, anchored in (
                ("Sign in", "sign-in"),
                ("What to do when it fails?", "what-to-do-when-it-fails"),
                ("C++ & Go", "c--go"), ("1. Restart", "1-restart"),
                ("snake_case and kebab-case", "snake_case-and-kebab-case"),
                ("Größe – Ünits", "größe--ünits"), ("日本語 テスト", "日本語-テスト"),
                ("Emoji 🚀 here", "emoji--here"), ("???", "")):
            with self.subTest(words=words):
                self.assertEqual(anchor(words), anchored)

    def test_a_handbooks_headings_take_their_anchors_and_a_repeat_counts(self):
        drawn = parse(str(render_markdown(
            "# Web\n\n## Sign in\n\n## `ssh` and **sudo**\n\n### {error}: restart"
            "\n\n## Sign in\n\n## Sign in\n\n## ???\n\n## ???\n\nSetext\n---\n",
            anchors=True)))
        headings = [found for found in drawn.all()
                    if found.tag in ("h1", "h2", "h3")]
        self.assertEqual([found.attrs.get("id") for found in headings],
                         ["web", "sign-in", "ssh-and-sudo", "error-restart",
                          "sign-in-1", "sign-in-2", None, "-1", "setext"])

    def test_no_other_text_is_anchored(self):
        self.assertNotIn("id=", str(render_markdown("## Sign in")))

    def test_a_link_to_a_section_stays_in_the_page(self):
        out = str(render_markdown("[Sign in](#sign-in) or [docs](https://e.com/#x)",
                                  anchors=True))
        self.assertIn('<a href="#sign-in">Sign in</a>', out)
        self.assertEqual(out.count('target="_blank"'), 1)


#: The address of the handbook of the node a text is rendered for, here.
HANDBOOK = "/handbook/svc/api"


class ShortFormTests(TestCase):
    """A text links its own node's handbook by a short form (ADR-0133 decision 4):
    ``handbook`` for its top and ``handbook#<section>`` for a section, which the
    renderer, handed the address of that node's handbook, leads there."""

    def test_it_leads_into_the_handbook_of_the_node_the_text_belongs_to(self):
        drawn = parse(str(render_markdown(
            "[What to do](handbook#when-it-fails), [the runbook](handbook).",
            handbook=HANDBOOK)))
        links = drawn.all(tag="a")
        self.assertEqual([link.attrs["href"] for link in links],
                         [f"{HANDBOOK}#when-it-fails", HANDBOOK])
        # a page of its own, as every other link opens
        self.assertTrue(all(link.attrs.get("target") == "_blank" for link in links))

    def test_inline_and_in_the_hover_cards_first_block_alike(self):
        self.assertIn(f'href="{HANDBOOK}#sign-in"', str(render_markdown_inline(
            "[Sign in](handbook#sign-in)", handbook=HANDBOOK)))
        block, _ = first_block("[Sign in](handbook#sign-in)\n\nMore.",
                               handbook=HANDBOOK)
        self.assertIn(f'href="{HANDBOOK}#sign-in"', str(block))

    def test_a_reference_a_table_and_a_section_as_the_link_spells_it(self):
        out = str(render_markdown(
            "[Sign in][s]\n\n| [a](handbook#b) |\n|---|\n\n[c](<handbook#d e>)\n\n"
            "[s]: handbook#sign-in", handbook=HANDBOOK))
        for href in (f"{HANDBOOK}#sign-in", f"{HANDBOOK}#b", f"{HANDBOOK}#d%20e"):
            self.assertIn(f'href="{href}"', out)

    def test_the_address_is_asked_for_only_where_a_link_leads_there(self):
        asked: list[str] = []

        def address() -> str:
            asked.append("asked")
            return HANDBOOK
        render_markdown("{error}: no link here, [docs](https://e.org/handbook#x).",
                        handbook=address)
        self.assertEqual(asked, [])
        render_markdown("[a](handbook) and [b](handbook#c)", handbook=address)
        self.assertEqual(len(asked), 2)

    def test_on_the_handbooks_own_page_it_is_a_section_of_the_page(self):
        out = str(render_markdown("[Sign in](handbook#sign-in), [top](handbook)",
                                  anchors=True, handbook=HANDBOOK))
        self.assertIn('<a href="#sign-in">Sign in</a>', out)
        self.assertIn('<a href="#">top</a>', out)
        self.assertNotIn("target=", out)

    def test_a_text_that_belongs_to_no_node_keeps_its_words_and_no_link(self):
        out = str(render_markdown(
            "See [the runbook](handbook#sign-in), and [docs](https://e.org)."))
        self.assertIn("See the runbook, and <a", out)
        self.assertEqual(out.count("<a "), 1)
        self.assertEqual(out.count("</a>"), 1)

    def test_what_is_no_short_form_is_left_alone(self):
        for text in ("`[a](handbook#x)`", "\\[a](handbook#x)", "[a](handbook.md)",
                     "[a](./handbook#x)", "[a](Handbook#x)", "[a](handbook/x)",
                     "![a](handbook#x)", "[a](https://e.org/handbook#x)"):
            with self.subTest(text=text):
                self.assertNotIn(HANDBOOK, str(render_markdown(text,
                                                               handbook=HANDBOOK)))


class AnchorsAndShortLinksTests(TestCase):
    """What the startup record compares (ADR-0133 decision 4): the sections a
    handbook's page anchors, and where each link a text writes in the short form
    leads, the text read as the page renders it."""

    def test_the_sections_are_the_anchors_of_the_handbooks_page(self):
        self.assertEqual(
            anchors_of("# Web\n\n## Sign in\n\n## Sign in\n\n### {error}: no "
                       "answers\n\n## Über uns\n\n    ## code\n"),
            frozenset({"web", "sign-in", "sign-in-1", "error-no-answers",
                       "über-uns"}))
        self.assertEqual(anchors_of(""), frozenset())

    def test_each_link_in_the_short_form_as_the_page_reads_the_text(self):
        text = ("[a](handbook) [b](handbook#x) `[c](handbook#y)` [d][r] "
                "[e](https://e.org/handbook#z)\n\n    [f](handbook#w)\n\n"
                "[r]: handbook#v")
        self.assertEqual(short_links(text), ["", "#x", "#v"])
        # a title is read on one line, where indentation makes no code block
        self.assertEqual(short_links("    [f](handbook#w)", inline=True), ["#w"])


class StatusSignTests(TestCase):
    """A status a text names in a placeholder's braces — `{error}` and the other four,
    in either case — is drawn as the status's sign, its cue and its word (ADR-0133
    decision 5), in every text the page shows: one renderer draws them all (ADR-0018
    decision 14)."""

    def _signs(self, markup: str) -> list[str]:
        return [element.text() for element in parse(markup).all("ls-sign")]

    def test_each_of_the_five_is_its_cue_and_its_word_on_its_tint(self):
        for status in StatusCode:
            word = status.name.lower()
            with self.subTest(status=word):
                drawn = parse(str(render_markdown_inline(f"{{{word}}}")))
                found = drawn.one("ls-sign")
                self.assertTrue(found.has(f"ls-sign--{word}"))
                self.assertEqual(found.text(), word)
                # the cue the wall draws, referring to the page's shape; decorative,
                # since the word speaks
                cue = found.one(tag="svg")
                self.assertTrue(cue.has("status-cue"))
                self.assertEqual(cue.attrs.get("aria-hidden"), "true")
                self.assertEqual(cue.one(tag="use").attrs["href"], f"#ls-cue-{word}")
                self.assertEqual(str(render_markdown_inline(f"{{{word}}}")),
                                 sign(status))

    def test_in_either_case_and_as_the_page_says_the_word(self):
        self.assertEqual(self._signs(str(render_markdown_inline(
            "{ERROR}, {Warn} and {ok}"))), ["error", "warn", "ok"])

    def test_every_text_draws_one_inline_or_as_a_block(self):
        # a title on its line, and every other text as a block: one renderer
        for markup in (render_markdown_inline("{error}: restart it"),
                       render_markdown("{error}: restart it")):
            with self.subTest(markup=str(markup)):
                self.assertEqual(self._signs(str(markup)), ["error"])

    def test_a_sentence_reads_round_it(self):
        out = parse(str(render_markdown(
            "{error}: open the run and add its analysis; *{warn}* waits, and "
            "[{undefined} here](https://example.org/runbook) is new.")))
        self.assertEqual(out.text(), "error: open the run and add its analysis; warn "
                                     "waits, and undefined here is new.")
        self.assertTrue(out.one("ls-sign--warn").within(out.one(tag="em")))
        self.assertTrue(out.one("ls-sign--undefined").within(out.one(tag="a")))

    def test_what_names_no_status_or_is_written_as_text_stays_as_written(self):
        for text, kept in (
                ("`{error}` is how an about names it", "<code>{error}</code>"),
                ("\\{error} is the placeholder", "{error} is the placeholder"),
                ("{erorr} and {errors} and { error } and {default}",
                 "{erorr} and {errors} and { error } and {default}"),
                ("see https://example.org/run/{error}/log",
                 ">https://example.org/run/{error}/log</a>")):
            with self.subTest(text=text):
                out = str(render_markdown(text))
                self.assertNotIn("ls-sign", out)
                self.assertIn(kept, out)

    def test_an_image_says_the_status_in_its_alternative_text(self):
        # a sign has no place in an attribute: the word stands there, and an image
        # whose words are one status is still described by it
        for text, alt in (("![{error} badge](https://x.org/b.png)", "error badge"),
                          ("![{ok}](https://x.org/i.png)", "ok")):
            with self.subTest(text=text):
                image = parse(str(render_markdown(text))).one(tag="img")
                self.assertEqual(image.attrs["alt"], alt)

    def test_only_the_five_names_in_ascii_s_case_name_a_status(self):
        for token, names in (("error", True), ("OK", True), ("Maintenance", True),
                             ("o\u212a", False), ("undef\u0130ned", False),
                             ("errors", False), ("default", False), ("", False)):
            with self.subTest(token=token):
                self.assertEqual(names_a_status(token), names)
                drawn = render_markdown_inline(f"{{{token}}}: x")
                self.assertEqual("ls-sign" in drawn, names)

    def test_a_code_block_keeps_it(self):
        for text in ("```\n{error}\n```", "    {error}"):
            with self.subTest(text=text):
                out = str(render_markdown(text))
                self.assertNotIn("ls-sign", out)
                self.assertIn("{error}", out)


class WriteSignsTests(TestCase):
    """Where a text leaves the instance, the library writes each sign the page draws
    in it out in a document's words (ADR-0133 decision 5) — and only those: the same
    parse and the same rule decide, block or inline as the page renders the text, so a
    placeholder the page shows as written stays as written."""

    @staticmethod
    def _out(text: str, inline: bool = False) -> str:
        return write_out(text, lambda code: f"<{code.name.lower()}>", inline=inline)

    def test_each_sign_is_written_in_the_words_given(self):
        self.assertEqual(self._out("{error}: restart it; {WARN} waits, {Ok} is fine."),
                         "<error>: restart it; <warn> waits, <ok> is fine.")

    def test_wherever_the_block_stands(self):
        for text, written in (
                ("# {error} #", "# <error> #"),
                ("## a {warn} b ##  ", "## a <warn> b ##  "),
                ("Under {error}\n===", "Under <error>\n==="),
                ("> quoted {error}\n> more {ok}", "> quoted <error>\n> more <ok>"),
                ("- item {warn}\n  lazy {error}", "- item <warn>\n  lazy <error>"),
                ("1.\t{error}\n\tmore {warn}", "1.\t<error>\n\tmore <warn>"),
                ("- a\n \t{error}", "- a\n \t<error>"),
                ("a line  \n  {ok} after a break  ",
                 "a line  \n  <ok> after a break  "),
                ("* [{error}](https://example.org/{warn}) *{warn}*",
                 "* [<error>](https://example.org/{warn}) *<warn>*"),
                # a block opened by a line blank only to Python, which markdown-it-py
                # strips away, and a NUL, which it reads as U+FFFD
                ("\u00a0\n{error} after a no-break space",
                 "\u00a0\n<error> after a no-break space"),
                ("- \u00a0\n  {error}", "- \u00a0\n  <error>"),
                ("a\x00 {error}", "a\x00 <error>")):
            with self.subTest(text=text):
                self.assertEqual(self._out(text), written)

    def test_what_the_page_shows_as_written_stays_as_written(self):
        for text in ("`{error}` in a code span", "\\{error} escaped",
                     "```\n{error}\n```", "~~~\n{error}\n~~~", "    {error} indented",
                     " -\t\t{error} indented in an item", "{errors} and {default}",
                     "https://example.org/run/{error}/log",
                     # a Kelvin sign is no k, and a dotted capital I no i
                     "{o\u212a} and {undef\u0130ned}"):
            with self.subTest(text=text):
                self.assertEqual(self._out(text), text)

    def test_inline_as_the_page_renders_a_title(self):
        # inline there is no code block, no fence and no reference definition: the
        # page draws a sign in each, and the text is written so
        for text, written in (
                ("    {error} when the probe fails",
                 "    <error> when the probe fails"),
                ("~~~\n{error}\n~~~", "~~~\n<error>\n~~~"),
                ("Reads x.\n\n\t{error}", "Reads x.\n\n\t<error>"),
                ("[{error}]\n\n[{error}]: https://example.org/",
                 "[<error>]\n\n[<error>]: https://example.org/")):
            with self.subTest(text=text):
                self.assertEqual(self._out(text, inline=True), written)
                self.assertEqual(len(parse(str(render_markdown_inline(
                    text))).all("ls-sign")), written.count("<"))

    def test_a_reference_label_and_an_image_s_words_stay_as_written(self):
        # the page links the label, whose definition would no longer answer to it
        # written out; and an image says the word in its alternative text
        for text in ("See [{error}].\n\n[{error}]: https://example.org/rb",
                     "See [{error} runbook][].\n\n[{error} runbook]: https://x.org/",
                     "![{error} badge](https://example.org/badge.png)"):
            with self.subTest(text=text):
                self.assertEqual(self._out(text), text)
        # a full reference's label is its key, and its words are written
        self.assertEqual(
            self._out("See [{error}: the runbook][rb].\n\n[rb]: https://x.org/"),
            "See [<error>: the runbook][rb].\n\n[rb]: https://x.org/")

    def test_in_a_table_s_cells(self):
        # a cell is a stretch of its row: found after the cell before it, with its
        # escaped pipes as the source writes them
        for text, written in (
                ("| a | {error} |\n|---|---|\n| {ok} | b |",
                 "| a | <error> |\n|---|---|\n| <ok> | b |"),
                ("| {error} | {error} |\n|-|-|", "| <error> | <error> |\n|-|-|"),
                ("| `{error}` | {error} |\n|---|---|",
                 "| `{error}` | <error> |\n|---|---|"),
                ("| x \\| y {warn} | z {ok} |\n|---|---|",
                 "| x \\| y <warn> | z <ok> |\n|---|---|"),
                ("> | {error} |\n> |---|", "> | <error> |\n> |---|"),
                ("{ok} | x\n--- | ---\na | ~~{warn}~~",
                 "<ok> | x\n--- | ---\na | ~~<warn>~~")):
            with self.subTest(text=text):
                self.assertEqual(self._out(text), written)

    def test_line_endings_change_only_where_a_sign_is_written(self):
        self.assertEqual(self._out("one\r\ntwo\r\n"), "one\r\ntwo\r\n")
        self.assertEqual(self._out("`{error}`\r\n"), "`{error}`\r\n")
        self.assertEqual(self._out("one\r\n{error}\r\n"), "one\n<error>\n")


#: Where a page draws a sign, by its word.
_DRAWN = re.compile(r'<span class="ls-sign ls-sign--(\w+)">')


def _drawn(text: str, inline: bool) -> list[str]:
    return _DRAWN.findall(str(render_markdown_inline(text) if inline
                              else render_markdown(text)))


class WriteSignsAgreesWithThePageTests(TestCase):
    """What :func:`write_out` writes is what the page draws, on texts written to
    trip the one over the other. The page says where it draws by counting: spoil one
    placeholder and it draws one sign fewer exactly where that one was a sign. A
    reference link's label that names a status and an image's words are what the
    write-out leaves as written on purpose, and stand elsewhere."""

    BLOCK = ("{error}: restart it; {WARN} waits.", "# {error} #", "Under {ok}\n---",
             "> a {ok}\n> b {error}", "- a {warn}\n  lazy {error}",
             "1.\t{error}\n\tmore {warn}", "- a\n \t{error}", "    {error} code",
             "```\n{error}\n```", "~~~\n{error}\n~~~", "`{error}` and {ok}",
             "\\{error} and {warn}", "[{error} x](https://example.org/{warn} \"{ok}\")",
             "<https://example.org/{error}> {ok}", "https://example.org/{error}/x {ok}",
             "*{error}* **{warn}** _{ok}_", "a  \n  {ok} b", "\u00a0\n{error}",
             "- \u00a0\n  {error}", "x\x00 {error}", "é {error} 🛠 {maintenance}",
             "{error}{warn}{ok}", "> - {error}\n>   {warn}", "- > {error}\n  > {ok}",
             "&#123;error} {error}", "{erorr} {error}", "line\r\n{error}\r\n",
             "Text.\n\n- one {ok}\n\n  two {error}\n\n> {undefined}",
             "| a | {error} |\n|---|:-:|\n| {ok} | `{warn}` |",
             "| {error} | {error} |\n|-|-|", "| `{error}` | {error} |\n|---|---|",
             "| x \\| {error} | {ok} |\n|---|---|", "~~{error}~~ and {ok}",
             "| {error} \\\\| x | {ok} |\n|---|---|")
    INLINE = ("    {error} when it fails", "\t{error}", "~~~\n{error}\n~~~",
              "Reads x.\n\n    {error}", "# {error}", "- {error} and {ok}",
              "`{error}` and {ok}")

    @staticmethod
    def _where_drawn(text: str, inline: bool) -> str:
        source = re.sub(r"\r\n?", "\n", text)
        drawn = len(_drawn(source, inline))
        expected, done = [], 0
        for found in re.finditer(r"\{(ok|warn|error|maintenance|undefined)\}",
                                 source, re.IGNORECASE | re.ASCII):
            word = found.group(1)
            spoiled = (source[:found.end(1) - 1] + ("z" if word[-1] == "q" else "q")
                       + source[found.end(1):])
            if len(_drawn(spoiled, inline)) == drawn - 1:
                expected.extend((source[done:found.start()], f"<{word.lower()}>"))
                done = found.end()
        expected.append(source[done:])
        written = "".join(expected)
        return written if written != source else text

    def test_it_writes_where_the_page_draws(self):
        for inline, texts in ((False, self.BLOCK), (True, self.INLINE)):
            for text in texts:
                with self.subTest(text=text, inline=inline):
                    self.assertEqual(
                        write_out(text, lambda code: f"<{code.name.lower()}>",
                                  inline=inline),
                        self._where_drawn(text, inline))


class PlainHelperTests(TestCase):
    def test_escapes_inline_specials(self):
        self.assertEqual(plain("*x*"), "\\*x\\*")
        self.assertEqual(plain("a`b"), "a\\`b")
        self.assertEqual(plain("[x](y)"), "\\[x\\](y)")

    def test_leaves_everyday_text_clean(self):
        # _ . - % / are not escaped: identifiers / hosts / flags stay readable
        for text in ("host.example", "MD0_DATA", "exit -1", "85% used on /"):
            self.assertEqual(plain(text), text)

    def test_non_str_is_stringified_then_escaped(self):
        # values read out of an untyped payload (JSON / YAML) arrive as int, Path,
        # exception — the escaping must apply to the *stringified* form
        self.assertEqual(plain(42), "42")
        self.assertEqual(plain(Path("/srv/*data*")), "/srv/\\*data\\*")
        self.assertEqual(plain(ValueError("bad `x`")), "bad \\`x\\`")

    def test_none_stringifies_rather_than_raising(self):
        # deliberate: a formatter on the untrusted-input boundary is total, so a
        # missing field renders visibly instead of taking out the whole reason
        self.assertEqual(plain(None), "None")

    def test_escaped_text_renders_literally(self):
        out = str(render_markdown_inline(plain(
            "*no* and [no](link) at HTTPS://external.example/path")))
        self.assertNotIn("<em>", out)
        self.assertNotIn("<a", out)
        self.assertIn("*no*", out)
        self.assertIn("HTTPS://external.example/path", out)

    def test_a_status_placeholder_stays_the_text_it_was(self):
        # in every text a placeholder is a sign (ADR-0133 decision 5): plain escapes
        # its brace alone, so every other brace stays clean
        self.assertEqual(plain("{error} and {OK}"), "\\{error} and \\{OK}")
        for text in ('{"level": "error"}', "{x}", "{errors}", "f'{error!r}'"):
            with self.subTest(text=text):
                self.assertEqual(plain(text), text)
        out = str(render_markdown_inline(plain("mount {error} at /srv")))
        self.assertNotIn("ls-sign", out)
        self.assertIn("mount {error} at /srv", out)


    def test_a_run_of_tildes_cannot_strike_the_text_through(self):
        # GitHub's strikethrough (ADR-0018 decision 14): each tilde of a run escaped,
        # and a lone one — a home directory's — left clean
        self.assertEqual(plain("a ~~b~~ c"), "a \\~\\~b\\~\\~ c")
        self.assertEqual(plain("~/data and x~y"), "~/data and x~y")
        out = str(render_markdown(plain("cleaned ~~old~~ files in ~/tmp")))
        self.assertNotIn("<s>", out)
        self.assertIn("cleaned ~~old~~ files in ~/tmp", out)


class TableTests(TestCase):
    """GitHub's tables and strikethrough in every text the page shows (ADR-0018
    decision 14): one renderer, so whoever writes a text never asks where it will
    stand."""

    def test_a_table_and_a_strikethrough_are_drawn(self):
        out = parse(str(render_markdown(
            "| Who | How |\n|---|:-:|\n| platform | ~~mail~~ chat |")))
        self.assertEqual([cell.text() for cell in out.all(tag="th")], ["Who", "How"])
        self.assertEqual([cell.text() for cell in out.all(tag="td")],
                         ["platform", "mail chat"])
        self.assertEqual(out.one(tag="s").text(), "mail")
        self.assertEqual(out.all(tag="td")[1].attrs.get("style"), "text-align:center")

    def test_a_title_strikes_through_on_its_line(self):
        out = str(render_markdown_inline("~~Old~~ gateway"))
        self.assertEqual(out, "<s>Old</s> gateway")

    def test_a_status_in_a_cell_is_its_sign(self):
        out = parse(str(render_markdown("| {error} | restart it |\n|---|---|")))
        self.assertEqual(out.all(tag="th")[0].one("ls-sign").text(), "error")

    def test_what_is_no_table_stays_text(self):
        # a delimiter row of its own is what makes one: a line with pipes is a line
        for text in ("a | b | c", "| a | b |", "a | b\nc | d"):
            with self.subTest(text=text):
                self.assertNotIn("<table>", str(render_markdown(text)))


class CodeHelperTests(TestCase):
    def test_wraps_in_a_fence(self):
        self.assertEqual(code("hello"), "```\nhello\n```")

    def test_multiline_is_preserved_and_inert(self):
        out = str(render_markdown(code("line1\n**still**\nline3")))
        self.assertIn("<pre>", out)
        self.assertIn("**still**", out)       # inside the fence — not rendered
        self.assertNotIn("<strong>", out)

    def test_non_str_is_stringified(self):
        self.assertEqual(code(42), "```\n42\n```")

    def test_fence_grows_past_backticks_inside_a_non_str(self):
        # regression: the backtick scan used to walk the *argument*, so a non-str
        # iterable was walked element-wise and its backticks never grew the fence —
        # the block then broke out of itself when rendered
        fenced = code(["a ``` b"])
        self.assertTrue(fenced.startswith("````"))
        out = str(render_markdown(fenced))
        self.assertIn("<pre>", out)
        self.assertIn("```", out)

    def test_fence_grows_past_inner_backticks(self):
        fenced = code("a ``` b")
        self.assertTrue(fenced.startswith("````"))   # 4 > the inner run of 3
        out = str(render_markdown(fenced))
        self.assertIn("<pre>", out)
        self.assertIn("```", out)                    # inner triple survives as text


#: The full address a written-out short form leads to, as a Copy document has it.
ADDRESS = "https://mon.example.org/handbook/svc/api"


def _sign(code: StatusCode) -> str:
    return f"<{code.name.lower()}>"


class WriteOutTheShortFormTests(TestCase):
    """Where a text leaves the instance, each link the page leads into the node's
    handbook is written out to the handbook's full address (ADR-0133 decision 4) —
    and only those, as the page reads the text."""

    def _out(self, text: str, inline: bool = False, handbook: str = ADDRESS) -> str:
        return write_out(text, _sign, handbook=handbook, inline=inline)

    def test_a_link_its_section_as_written(self):
        self.assertEqual(
            self._out("[What to do](handbook#when-it-fails), [top](handbook). {error}"),
            f"[What to do]({ADDRESS}#when-it-fails), [top]({ADDRESS}). <error>")

    def test_in_angle_brackets_a_reference_a_title_and_a_cell(self):
        for text, written, inline in (
                ("[a](<handbook#b c>)", f"[a](<{ADDRESS}#b c>)", False),
                ("[a][r]\n\n[r]: handbook#s \"T\"",
                 f"[a][r]\n\n[r]: {ADDRESS}#s \"T\"", False),
                ("[a][]\n\n[a]:\n  handbook#s", f"[a][]\n\n[a]:\n  {ADDRESS}#s",
                 False),
                ("Web [runbook](handbook) {ok}", f"Web [runbook]({ADDRESS}) <ok>",
                 True),
                ("| [a](handbook#b) | {ok} |\n|---|---|",
                 f"| [a]({ADDRESS}#b) | <ok> |\n|---|---|", False),
                ("> - [a](handbook#b)\n>   more", f"> - [a]({ADDRESS}#b)\n>   more",
                 False)):
            with self.subTest(text=text):
                self.assertEqual(self._out(text, inline), written)

    def test_what_the_page_shows_as_written_stays_so(self):
        for text in ("`[a](handbook#b)`", "\\[a](handbook#b)", "    [a](handbook#b)",
                     "[a](handbook#b c)", "![a](handbook#b)", "[a](handbook.md)"):
            with self.subTest(text=text):
                self.assertEqual(self._out(text), text)

    def test_without_an_address_the_short_form_stays_as_written(self):
        self.assertEqual(self._out("[a](handbook#b) {ok}", handbook=""),
                         "[a](handbook#b) <ok>")

    def test_an_address_with_parentheses_and_a_short_form_spelled_otherwise(self):
        address = "https://mon.example.org/handbook/svc/api(v2)"
        self.assertEqual(
            self._out("[a](handbook#b) [c](&#104;andbook#d)", handbook=address),
            "[a](https://mon.example.org/handbook/svc/api%28v2%29#b) "
            "[c](https://mon.example.org/handbook/svc/api%28v2%29#d)")


def _led(text: str, inline: bool) -> int:
    rendered = (render_markdown_inline(text, handbook=ADDRESS) if inline
                else render_markdown(text, handbook=ADDRESS))
    return str(rendered).count(f'href="{ADDRESS}')


class WriteOutAgreesWithTheLinksTests(TestCase):
    """What :func:`write_out` writes out is what the page leads into the handbook, on
    texts written to trip the one over the other. The page says where it leads by
    counting: spoil one ``handbook`` and it leads one link fewer exactly where that
    one was a link's destination, or a definition's."""

    BLOCK = ("[a](handbook#x) and [b](handbook)", "`[c](handbook#y)` [d](handbook#z)",
             "\\[e](handbook#q) [f](<handbook#g h>)", "[i][r]\n\n[r]: handbook#j",
             "[k][]\n\n[k]:\n  handbook#l 'T'", "> [m](handbook#n)\n> - [o](handbook)",
             "| [p](handbook#q) | handbook |\n|---|---|",
             "[handbook](handbook#handbook)",
             "[s](handbook#t \"handbook\")", "    [u](handbook#v)",
             "[w](https://e.org/handbook#x) [y](handbook.md)",
             "![z](handbook#a) [b](handbook)",
             "[d](handbook#e)[f](handbook#g)", "[h](\n  handbook#i\n)",
             "line\r\n[j](handbook#k)\r\n", "- \u00a0\n  [l](handbook#m)",
             "[n](handbook#o) {error}", "[p] [p]\n\n[p]: handbook#q",
             "~~[r](handbook#s)~~", "*[t](handbook)* **[u](handbook#v)**")
    INLINE = ("    [a](handbook#b)", "Web [runbook](handbook) {ok}", "`[c](handbook)`")

    @staticmethod
    def _where_led(text: str, inline: bool) -> str:
        source = re.sub(r"\r\n?", "\n", text)
        led = _led(source, inline)
        expected, done = [], 0
        for found in re.finditer("handbook", source):
            spoiled = source[:found.start()] + "handbooq" + source[found.end():]
            if _led(spoiled, inline) < led:
                expected.extend((source[done:found.start()], ADDRESS))
                done = found.end()
        expected.append(source[done:])
        written = "".join(expected)
        return written if written != source else text

    def test_it_writes_out_where_the_page_leads(self):
        for inline, texts in ((False, self.BLOCK), (True, self.INLINE)):
            for text in texts:
                with self.subTest(text=text, inline=inline):
                    self.assertEqual(
                        write_out(text, str, handbook=ADDRESS, inline=inline)
                        if "{" not in text else
                        write_out(text, _sign, handbook=ADDRESS, inline=inline)
                        .replace("<error>", "{error}").replace("<ok>", "{ok}"),
                        self._where_led(text, inline))
