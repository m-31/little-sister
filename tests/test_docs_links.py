"""Doc hygiene: every relative Markdown link must resolve.

Each ``](target)`` link in the repo's tracked Markdown must point to a real file
(and, when it carries a ``#fragment``, a real heading anchor). External URLs are
out of scope; fenced and inline code is ignored so example link-syntax isn't
flagged. Backstops the "verify cross-references" rule in AGENTS.md.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_FENCE = re.compile(r"^\s*(?:```|~~~)")
_INLINE_CODE = re.compile(r"``.+?``|`[^`]*`")
_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_EXTERNAL = ("http://", "https://", "mailto:", "tel:", "//")


def _markdown_files() -> list[Path]:
    """Tracked Markdown files (falls back to a filtered walk without git)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "*.md"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        tracked = [REPO_ROOT / line for line in result.stdout.split()]
        if tracked:
            return tracked
    except (OSError, subprocess.SubprocessError):
        pass
    skip = {".git", ".venv", "venv", ".idea", "node_modules", "__pycache__"}
    return [p for p in REPO_ROOT.rglob("*.md")
            if not any(part in skip for part in p.parts)]


def _content_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) for every line outside a fenced code block."""
    lines: list[tuple[int, str]] = []
    in_fence = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if _FENCE.match(raw):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append((lineno, raw))
    return lines


def _heading_anchors(text: str) -> set[str]:
    """GitHub-style heading slugs defined in a Markdown document."""
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for _, raw in _content_lines(text):
        match = _HEADING.match(raw)
        if not match:
            continue
        slug = re.sub(r"[^\w\s-]", "", match.group(1).strip().lower())
        slug = re.sub(r"\s", "-", slug).strip("-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def test_relative_markdown_links_resolve() -> None:
    anchors: dict[Path, set[str]] = {}
    broken: list[str] = []
    for md in _markdown_files():
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8")
        for lineno, raw in _content_lines(text):
            line = _INLINE_CODE.sub("", raw)
            for match in _LINK.finditer(line):
                inner = match.group(1).strip()
                if not inner:
                    continue
                target = inner.split(None, 1)[0].strip("<>")
                if not target or target.startswith(_EXTERNAL):
                    continue
                path_part, _, fragment = target.partition("#")
                where = f"{md.relative_to(REPO_ROOT)}:{lineno}"
                dest = md if not path_part else (md.parent / path_part)
                if path_part and not dest.exists():
                    broken.append(f"{where} -> {target} (missing file)")
                    continue
                if fragment and dest.suffix == ".md" and dest.exists():
                    if dest not in anchors:
                        anchors[dest] = _heading_anchors(
                            dest.read_text(encoding="utf-8"))
                    if fragment.lower() not in anchors[dest]:
                        broken.append(f"{where} -> {target} (missing anchor)")
    assert not broken, "Broken Markdown links:\n  " + "\n  ".join(broken)
