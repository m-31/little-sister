"""Chromium holds the icons little-sister serves to the drawing they come from.

``tests/render_brand.py`` renders every icon under ``src/little_sister/static/`` from
``src/little_sister/brand/``. This renders them again and compares each committed
image with its fresh render, pixel by pixel, allowing what a rasterizer moves on its
own from one build to another: an icon edited by hand, or one whose digest was copied
from another, fails here, and ``prep`` refuses the release. Skipped where Playwright
or a Chromium binary is unavailable, like every browser file.
"""
from __future__ import annotations

import base64
import unittest
from typing import Any

from tests import render_brand

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: How far a pixel may move between two renders of one drawing — measured on
#: premultiplied channels, so a transparent pixel's color is not compared — and the
#: share of pixels that may move further, which a small icon, all edge, needs more of.
#: Generous on purpose: Cairo, another rasterizer altogether, stays inside it, at
#: 4.3 % of a 16 px icon and 0.22 % of a 180 px one, while a stale icon moves more
#: than a third of its pixels and the eyeshadow left out 3.7 % of a home-screen
#: icon's. That an image is the drawing as it is now, exactly, is
#: ``tests/test_brand.py``'s, which reads the digest the image carries.
_NEAR = 32


def _share(px: int) -> float:
    return 0.05 if px <= 48 else 0.01

_DIFFERENCE = """
async ([a, b, px, near]) => {
  const load = src => new Promise((ok, no) => {
    const image = new Image();
    image.onload = () => ok(image);
    image.onerror = no;
    image.src = src;
  });
  const pixels = async src => {
    const canvas = new OffscreenCanvas(px, px);
    const context = canvas.getContext('2d');
    context.drawImage(await load(src), 0, 0, px, px);
    return context.getImageData(0, 0, px, px).data;
  };
  const p = await pixels(a), q = await pixels(b);
  let far = 0;
  for (let i = 0; i < p.length; i += 4) {
    let d = Math.abs(p[i + 3] - q[i + 3]);
    for (let c = 0; c < 3; c++) {
      d = Math.max(d, Math.abs(p[i + c] * p[i + 3] - q[i + c] * q[i + 3]) / 255);
    }
    if (d > near) far++;
  }
  return far / (px * px);
}
"""


def _uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


class TheIconsAreTheDrawing(unittest.TestCase):
    playwright: Any = None
    browser: Any = None
    page: Any = None
    fresh: dict[str, bytes]

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = render_brand.launch(cls.playwright)
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error
        cls.page = cls.browser.new_page(device_scale_factor=1)
        cls.fresh = render_brand.render_all(cls.page)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def _assert_renders_alike(self, what: str, committed: bytes, fresh: bytes,
                              px: int) -> None:
        share = self.page.evaluate(_DIFFERENCE,
                                   [_uri(committed), _uri(fresh), px, _NEAR])
        self.assertLessEqual(
            share, _share(px),
            f"{what}: {share:.1%} of its pixels differ from the drawing's render — "
            f"run `uv run --group browser python tests/render_brand.py`")

    def test_each_png_is_what_the_drawing_renders(self) -> None:
        for name, px in render_brand.TAB_PNGS + render_brand.TILES:
            with self.subTest(name):
                committed = (render_brand.STATIC / name).read_bytes()
                self._assert_renders_alike(name, committed, self.fresh[name], px)

    def test_the_ico_holds_the_drawing_at_16_32_and_48_px(self) -> None:
        committed = render_brand.ico_entries(
            (render_brand.STATIC / "favicon.ico").read_bytes())
        fresh = render_brand.ico_entries(self.fresh["favicon.ico"])
        self.assertEqual([px for px, _ in committed], list(render_brand.ICO_SIZES))
        for (px, ours), (_, theirs) in zip(committed, fresh, strict=True):
            with self.subTest(px=px):
                self._assert_renders_alike(f"favicon.ico at {px} px", ours, theirs, px)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
