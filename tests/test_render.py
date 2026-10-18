"""Markdown rendering and the reason-assembly helpers (ADR-0018)."""
from pathlib import Path
from unittest import TestCase

from pytest import mark

from little_sister.checks import code, plain
from little_sister.render import first_block, render_markdown, render_markdown_inline


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
