"""Render the icons little-sister serves from its drawing.

The drawing is ``src/little_sister/brand/``: ``eye.svg``, the full form, and
``eye-small.svg``, the form for 32 px and below. Every icon under
``src/little_sister/static/`` is rendered from it here, by Chromium::

    uv run --group browser python tests/render_brand.py

- ``favicon.svg`` — the small form with its eyeshadow, whose ink turns light on a
  dark tab strip; a tab only ever shows it small.
- ``favicon-16x16.png`` and ``favicon-32x32.png`` — the same, rendered.
- ``favicon.ico`` — 16, 32 and 48 px: the small form up to 32 px, the full one above.
- ``apple-touch-icon.png`` (180 px), ``android-chrome-192x192.png`` and
  ``android-chrome-512x512.png`` — the full form on rose paper, edge to edge, because
  the phone rounds the corners itself.

Each PNG, and each of the .ico's entries, carries the SHA-256 of the SVG it was
rendered from in a ``tEXt`` chunk, so ``tests/test_brand.py`` can tell without a
browser whether every icon is the drawing as it is now — and holds ``favicon.svg`` to
what this writes. ``tests/test_brand_browser.py`` holds the pixels.
"""
from __future__ import annotations

import base64
import hashlib
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "src" / "little_sister" / "brand"
STATIC = ROOT / "src" / "little_sister" / "static"

INK = "#343a40"  # the drawing's ink, the one it lets a renderer swap
DARK_INK = "#e9ecef"  # favicon.svg's ink on a dark tab strip
PAPER = ("#fff8fb", "#f3cfdd")  # a home-screen icon's ground, top to bottom
SMALL = 32  # at or below this many pixels the small form is drawn
TAB_SHARE = 61 / 64  # how much of a tab icon's width the eye spans
TILE_SHARE = 0.80  # and of a home-screen icon's
TILE_LIFT = 18 / 1024  # how far above the middle a home-screen icon's eye sits

#: (file, pixels) of the tab icons rendered as PNG, and of the .ico's entries
TAB_PNGS = (("favicon-16x16.png", 16), ("favicon-32x32.png", 32))
ICO_SIZES = (16, 32, 48)
#: (file, pixels) of the home-screen icons
TILES = (("apple-touch-icon.png", 180), ("android-chrome-192x192.png", 192),
         ("android-chrome-512x512.png", 512))

#: The ``tEXt`` keyword under which an image names the SVG it was rendered from
SOURCE_KEY = b"little-sister drawing"

#: A sandbox pins one browser build; a venv-installed Playwright may expect a
#: different one, so it is pointed at what is there.
SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def drawing(small: bool) -> tuple[str, tuple[float, float, float, float]]:
    """The drawing's content — everything inside its root, comments left out — and its
    view box."""
    name = "eye-small.svg" if small else "eye.svg"
    text = (BRAND / name).read_text(encoding="utf-8")
    root = re.search(r"<svg\b[^>]*>", text)
    if root is None:
        raise ValueError("the drawing has no <svg> root")
    box = re.search(r'viewBox="([^"]+)"', root.group(0))
    if box is None:
        raise ValueError("the drawing's root has no viewBox")
    x, y, w, h = (float(v) for v in box.group(1).split())
    inner = text[root.end():text.rindex("</svg>")]
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.DOTALL)
    return "\n".join(line for line in inner.splitlines() if line.strip()), (x, y, w, h)


def placed(box: tuple[float, float, float, float], size: float, share: float,
           lift: float = 0.0) -> str:
    """The transform that centers a view box in a square of *size*, its width *share*
    of the square's, raised by *lift* of it."""
    x, y, w, h = box
    k = size * share / w
    tx = size / 2 - k * (x + w / 2)
    ty = size / 2 - k * (y + h / 2) - lift * size
    return f"translate({tx:.3f},{ty:.3f}) scale({k:.5f})"


def favicon_svg() -> str:
    """``favicon.svg``: the small form, its ink a variable a dark tab strip re-inks."""
    content, box = drawing(small=True)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f"<style>:root{{--n:{INK}}}@media (prefers-color-scheme: dark)"
        f"{{:root{{--n:{DARK_INK}}}}}</style>\n"
        f'<g transform="{placed(box, 64, TAB_SHARE)}">\n'
        f"{content.replace(INK, 'var(--n)')}\n</g>\n</svg>\n"
    )


def tab_svg(px: int) -> str:
    """A tab icon of *px* pixels for a PNG or the .ico, which cannot re-ink."""
    content, box = drawing(small=px <= SMALL)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f'<g transform="{placed(box, 64, TAB_SHARE)}">{content}</g></svg>')


def tile_svg() -> str:
    """A home-screen icon: the full form on rose paper, edge to edge."""
    content, box = drawing(small=False)
    top, bottom = PAPER
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        '<defs><linearGradient id="paper" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/>'
        '</linearGradient></defs><rect width="1024" height="1024" fill="url(#paper)"/>'
        f'<g transform="{placed(box, 1024, TILE_SHARE, TILE_LIFT)}">{content}</g></svg>'
    )


def digest(svg: str) -> str:
    """What an image rendered from *svg* is stamped with."""
    return hashlib.sha256(svg.encode()).hexdigest()


def stamped(png: bytes, svg: str) -> bytes:
    """*png* with :func:`digest` of *svg* in a ``tEXt`` chunk after its header."""
    data = SOURCE_KEY + b"\0" + digest(svg).encode()
    chunk = (struct.pack(">I", len(data)) + b"tEXt" + data
             + struct.pack(">I", zlib.crc32(b"tEXt" + data)))
    header_end = 8 + 12 + 13  # the signature, then IHDR: 13 bytes and 12 around them
    return png[:header_end] + chunk + png[header_end:]


def drawn_from(png: bytes) -> str | None:
    """The digest *png* was stamped with by :func:`stamped`, or None."""
    i = 8
    while i + 8 <= len(png):
        (size,) = struct.unpack_from(">I", png, i)
        if png[i + 4:i + 8] == b"tEXt":
            key, _, value = png[i + 8:i + 8 + size].partition(b"\0")
            if key == SOURCE_KEY:
                return value.decode("latin-1")
        i += 12 + size
    return None


def render(page: Any, svg: str, px: int, opaque: bool) -> bytes:
    """*svg* as a PNG of *px* by *px*, rendered by the Chromium *page* drives and
    stamped with what it was rendered from."""
    page.set_viewport_size({"width": px, "height": px})
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    page.set_content(f'<body style="margin:0"><img src="{uri}" width="{px}" '
                     f'height="{px}" style="display:block"></body>')
    page.wait_for_function("document.images[0].complete")
    png: bytes = page.screenshot(omit_background=not opaque,
                                 clip={"x": 0, "y": 0, "width": px, "height": px})
    return stamped(png, svg)


def ico(entries: list[tuple[int, bytes]]) -> bytes:
    """A .ico holding each (pixels, PNG) entry as it is."""
    head = struct.pack("<HHH", 0, 1, len(entries))
    table, data, offset = b"", b"", 6 + 16 * len(entries)
    for px, png in entries:
        side = px if px < 256 else 0
        table += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    return head + table + data


def ico_entries(blob: bytes) -> list[tuple[int, bytes]]:
    """The (pixels, PNG) entries of a .ico — the inverse of :func:`ico`."""
    _, kind, count = struct.unpack_from("<HHH", blob)
    if kind != 1:
        raise ValueError("not an icon file")
    entries = []
    for i in range(count):
        side, _, _, _, _, _, size, offset = struct.unpack_from(
            "<BBBBHHII", blob, 6 + 16 * i)
        entries.append((side or 256, blob[offset:offset + size]))
    return entries


def render_all(page: Any) -> dict[str, bytes]:
    """Every icon the package serves, by its file name under ``static/``."""
    images = {name: render(page, tab_svg(px), px, opaque=False)
              for name, px in TAB_PNGS}
    images["favicon.ico"] = ico(
        [(px, render(page, tab_svg(px), px, opaque=False)) for px in ICO_SIZES])
    images.update({name: render(page, tile_svg(), px, opaque=True)
                   for name, px in TILES})
    return images


def launch(playwright: Any) -> Any:
    """Chromium, as this machine has it."""
    return playwright.chromium.launch(
        executable_path=str(SANDBOX_CHROMIUM) if SANDBOX_CHROMIUM.is_file() else None)


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = launch(p)
        try:
            page = browser.new_page(device_scale_factor=1)
            images = render_all(page)
        finally:
            browser.close()
    (STATIC / "favicon.svg").write_text(favicon_svg(), encoding="utf-8")
    print("favicon.svg")
    for name, blob in images.items():
        (STATIC / name).write_bytes(blob)
        print(f"{name}  {len(blob)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
