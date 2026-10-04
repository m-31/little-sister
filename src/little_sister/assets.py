"""Our own stylesheet and scripts, each named by its content (ADR-0112).

A page that is open keeps the files it was loaded with — the refresh swaps a part
of the document and fetches no stylesheet and no script — and a browser that loads
a page afresh may still be handed yesterday's file under today's URL. Both are
answered by one fact about a file: the first eight hex digits of its SHA-256, the
form a registered package's asset already takes (ADR-0037).

* :meth:`Assets.digest` is that fact for one file, and is what its URL carries, so
  a changed file is a changed URL and the answer to it can be kept for good.
* :meth:`Assets.set_digest` is one digest over the whole set, which a page states
  and every part it fetches states again: where the two differ, the process the
  page reads from links other files than the page holds.

Only stylesheets and scripts: they are what a page and the markup it is sent have
to agree on. A picture changes rarely, and is asked for by name from outside the
templates — a bookmark, a web manifest.

A file is hashed when it is first asked for and again when its size or its
modification time has moved, so an edit shows on the next page without a restart —
which is what the edit loop of ``docs/testing-the-gui.md`` needs, and costs a
``stat`` per file a page links.
"""
from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from pathlib import Path

#: What is hashed: the two kinds a page and its markup have to agree on.
SUFFIXES = (".css", ".js")

#: How many hex digits of a SHA-256 name a file — a registered package's asset
#: carries as many (:mod:`little_sister.slots`).
DIGITS = 8


class Assets:
    """The stylesheets and scripts beneath one directory, each with its hash."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._lock = threading.Lock()
        #: name → ((size, modification time), digest), for what was hashed last.
        self._seen: dict[str, tuple[tuple[int, int], str]] = {}

    def digest(self, name: str) -> str | None:
        """The hash ``name`` is addressed by, or ``None`` where it has none: a
        file of another kind, one that is not there, or a name that leaves the
        directory."""
        if not name.endswith(SUFFIXES):
            return None
        path = (self._root / name).resolve()
        if self._root not in path.parents:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        state = (stat.st_size, stat.st_mtime_ns)
        with self._lock:
            seen = self._seen.get(name)
            if seen is not None and seen[0] == state:
                return seen[1]
        try:
            payload = path.read_bytes()
        except OSError:
            return None
        digest = hashlib.sha256(payload).hexdigest()[:DIGITS]
        with self._lock:
            self._seen[name] = (state, digest)
        return digest

    def names(self) -> tuple[str, ...]:
        """Every stylesheet and script beneath the directory, by the name a URL
        gives it, in order."""
        return tuple(sorted(
            path.relative_to(self._root).as_posix()
            for path in self._root.rglob("*")
            if path.name.endswith(SUFFIXES) and path.is_file()))

    def set_digest(self, others: Iterable[str] = ()) -> str:
        """One digest over the whole set: every file's name with its hash, and
        ``others`` — the hashes of what the registered packages ship, which a page
        links beside ours."""
        whole = hashlib.sha256()
        for name in self.names():
            whole.update(f"{name}:{self.digest(name)}\n".encode())
        for other in others:
            whole.update(f"+{other}\n".encode())
        return whole.hexdigest()[:DIGITS]
