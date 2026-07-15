"""Markdown rendering and the reason-assembly helpers (ADR-0018)."""
from unittest import TestCase

from pytest import mark

from little_sister.checks import code, plain
from little_sister.render import render_markdown, render_markdown_inline


class RenderInlineTests(TestCase):
    def test_emphasis_code_and_link_render(self):
        out = str(render_markdown_inline("**b** `c` [x](https://e.com)"))
        self.assertIn("<strong>b</strong>", out)
        self.assertIn("<code>c</code>", out)
        self.assertIn('href="https://e.com"', out)

    def test_inline_has_no_paragraph_wrapper(self):
        self.assertNotIn("<p>", str(render_markdown_inline("hello")))

    def test_links_get_noopener(self):
        out = str(render_markdown_inline("[x](https://e.com)"))
        self.assertIn('rel="noopener noreferrer"', out)


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


class PlainHelperTests(TestCase):
    def test_escapes_inline_specials(self):
        self.assertEqual(plain("*x*"), "\\*x\\*")
        self.assertEqual(plain("a`b"), "a\\`b")
        self.assertEqual(plain("[x](y)"), "\\[x\\](y)")

    def test_leaves_everyday_text_clean(self):
        # _ . - % / are not escaped: identifiers / hosts / flags stay readable
        for text in ("host.example", "MD0_DATA", "exit -1", "85% used on /"):
            self.assertEqual(plain(text), text)

    def test_escaped_text_renders_literally(self):
        out = str(render_markdown_inline(plain("*no* and [no](link)")))
        self.assertNotIn("<em>", out)
        self.assertNotIn("<a", out)
        self.assertIn("*no*", out)


class CodeHelperTests(TestCase):
    def test_wraps_in_a_fence(self):
        self.assertEqual(code("hello"), "```\nhello\n```")

    def test_multiline_is_preserved_and_inert(self):
        out = str(render_markdown(code("line1\n**still**\nline3")))
        self.assertIn("<pre>", out)
        self.assertIn("**still**", out)       # inside the fence — not rendered
        self.assertNotIn("<strong>", out)

    def test_fence_grows_past_inner_backticks(self):
        fenced = code("a ``` b")
        self.assertTrue(fenced.startswith("````"))   # 4 > the inner run of 3
        out = str(render_markdown(fenced))
        self.assertIn("<pre>", out)
        self.assertIn("```", out)                    # inner triple survives as text
