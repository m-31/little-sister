"""little-sister's built-in icon pack: the marks the links page ships with.

Package data, not code — the SVG files beside this module are the point, and
:mod:`little_sister.icons` reads them through :mod:`importlib.resources`. It is a
package rather than a bare directory so a pack always names an importable package and
a bare file name inside it, which is what keeps a pack from reaching outside its own
data.

Every glyph here is **drawn for little-sister**: a generic figure for what the product
does — a cloud for ``aws``, a git graph for ``github`` — never the vendor's own mark.
That is what lets the pack ship at all. Redistributing a vendor's logo inside a wheel
is a question each vendor answers differently and some answer restrictively, while
drawing our own asks nobody: no redistribution question, no trademark question, it
works with no outbound access, and it themes as a proper light/dark pair. What it
costs is recognizability, and a deployment that wants the real mark says so in one
line of its own ``icons:`` map. See ``manifest.yaml`` for what each glyph depicts.
"""
