"""The icons little-sister serves are its drawing, ``src/little_sister/brand/``.

What holds without a browser: ``favicon.svg`` is the small form exactly as
``tests/render_brand.py`` writes it, re-inking itself on a dark tab strip; every
image names the SVG it was rendered from, and that is the drawing as it is now; the
two forms sit in the same place; and the eyeshadow is one layer, which a renderer
that wants the plain eye can leave out whole. ``tests/test_brand_browser.py`` holds
the images' pixels.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from unittest import TestCase

from tests import render_brand

_SVG = "{http://www.w3.org/2000/svg}"
_FORMS = ("eye.svg", "eye-small.svg")


def _form(name: str) -> ET.Element:
    return ET.parse(render_brand.BRAND / name).getroot()


class TheTabIconIsTheSmallForm(TestCase):
    def test_the_served_svg_is_what_the_renderer_writes_from_the_drawing(self) -> None:
        served = (render_brand.STATIC / "favicon.svg").read_text(encoding="utf-8")
        self.assertEqual(served, render_brand.favicon_svg())

    def test_it_is_drawn_small(self) -> None:
        small, _ = render_brand.drawing(small=True)
        full, _ = render_brand.drawing(small=False)
        served = (render_brand.STATIC / "favicon.svg").read_text(encoding="utf-8")
        self.assertIn(small.replace(render_brand.INK, "var(--n)"), served)
        self.assertNotIn(full.replace(render_brand.INK, "var(--n)"), served)

    def test_its_ink_turns_light_on_a_dark_tab_strip(self) -> None:
        served = (render_brand.STATIC / "favicon.svg").read_text(encoding="utf-8")
        self.assertIn(":root{--n:#343a40}@media (prefers-color-scheme: dark)"
                      "{:root{--n:#e9ecef}}", served)
        # the light ink is written once, in that rule, and nowhere in the drawing
        self.assertEqual(served.count("#343a40"), 1)


class EveryIconIsTheDrawingAsItIsNow(TestCase):
    def test_each_png_names_the_svg_it_was_rendered_from(self) -> None:
        wanted = [(name, render_brand.tab_svg(px))
                  for name, px in render_brand.TAB_PNGS]
        wanted += [(name, render_brand.tile_svg()) for name, _ in render_brand.TILES]
        for name, svg in wanted:
            with self.subTest(name):
                png = (render_brand.STATIC / name).read_bytes()
                self.assertEqual(render_brand.drawn_from(png), render_brand.digest(svg))

    def test_each_entry_of_the_ico_too(self) -> None:
        entries = render_brand.ico_entries(
            (render_brand.STATIC / "favicon.ico").read_bytes())
        self.assertEqual([px for px, _ in entries], list(render_brand.ICO_SIZES))
        for px, png in entries:
            with self.subTest(px=px):
                self.assertEqual(render_brand.drawn_from(png),
                                 render_brand.digest(render_brand.tab_svg(px)))


class TheTwoFormsSitInTheSamePlace(TestCase):
    def test_the_small_form_keeps_the_full_forms_view_box(self) -> None:
        self.assertEqual(_form("eye-small.svg").get("viewBox"),
                         _form("eye.svg").get("viewBox"))


class TheEyeshadowIsALayerOfItsOwn(TestCase):
    def test_each_form_holds_it_in_one_group(self) -> None:
        for name in _FORMS:
            with self.subTest(name):
                found = [e for e in _form(name).iter() if e.get("id") == "eyeshadow"]
                self.assertEqual([e.tag for e in found], [f"{_SVG}g"])

    def test_leaving_the_group_out_leaves_none_of_it(self) -> None:
        for name in _FORMS:
            with self.subTest(name):
                root = _form(name)
                for parent in root.iter():
                    for child in list(parent):
                        if child.get("id") == "eyeshadow":
                            parent.remove(child)
                plain = ET.tostring(root, encoding="unicode")
                self.assertNotIn("eyeshadow", plain)  # no reference left dangling
                self.assertNotIn("#a8235f", plain)    # and none of its color
                self.assertIn('id="eye-white"', plain)  # while the eye stays
