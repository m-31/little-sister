"""Captured output as a **reading**: the idiom the three command checks share.

``command``, ``ssh-command`` and ``ssh-script`` read no number. What they read is
an exit code and a blob of captured output, and the line they write *is* that
output, fenced. So under the measurement/grading split (ADR-0086) the output has
to be in the record — otherwise the grading, which may read nothing else, could
not write the sentence, and a reading out of a series could not be retold.

That makes ``record_limit`` the real ceiling on how much captured output a
deployment may keep, and ``max_chars`` a request within it. The bound is in
**bytes**, and that is the whole reason this module exists rather than a `[:n]`
in three places: a record is weighed as ``json.dumps`` writes it, which escapes
to ASCII. Measured against the 2 KB default, 1000 characters of output come to
1014 bytes in ASCII, 2014 when every one of them is a newline, and 6014 in
umlauts or CJK. A check that clipped by characters alone would declare a size it
could exceed threefold and be refused at the seam on every run — the exact
failure a declaration exists to prevent.

So the text is clipped **once**, to ``max_chars`` characters and then to whatever
byte budget is left, and that one result is both the record and the line. The
visible cost is honest: with non-ASCII output the line shows less than
``max_chars`` asked for, which beats a check that goes red every run. What it
buys is exact — :func:`output_record_bytes` is a ceiling that cannot be exceeded,
so startup either passes the configuration or refuses it by name, and the seam
never refuses a reading at runtime.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from little_sister.limits import RECORD_LIMIT
from little_sister.reasons import clip

#: What the failure text of a run that never produced an exit code is clipped to
#: — a timeout, a command that could not be started — and, through
#: :func:`failure_text`, the error of any reading that failed: `http` and `file`
#: clip theirs to the same two bounds, so one budget sizes every declaration that
#: carries one.
FAILURE_CHARS = 300
FAILURE_BYTES = 320

#: Everything in one of these records that is not the captured output: the keys
#: and syntax, an ``exit_code`` wide enough for any signal or status, and the
#: failure text above (never present beside output, but declared as though it
#: were, because a ceiling is not the place to be clever).
RECORD_OVERHEAD = 64 + FAILURE_BYTES

#: The worst a single character can cost inside a JSON string. Not six: an umlaut
#: is ``\\u00e4`` and costs six, but a character outside the basic plane — an
#: emoji in a log line — is written as a **surrogate pair**, ``\\ud83d\\ude00``,
#: and costs twelve. Measured, not reasoned about, because this number is what
#: makes the declaration below a ceiling rather than a hope: too small and a
#: check would exceed a size it declared, which is the one thing a declaration
#: must not do. Used only to size that declaration, never to clip — the clip
#: measures the real string.
WORST_BYTES_PER_CHAR = 12


def output_budget() -> int:
    """Bytes the captured output may occupy in a record.

    Against the **default** ``record_limit`` and not the deployment's, for the
    reason ADR-0075 gives: a type aims at the default because a package cannot
    see which deployment it is installed into — and because a reading that came
    out the same length everywhere is the one a series can be compared across.
    A deployment that lowered its limit is refused at startup by name; one that
    raised it simply does not get the extra room.
    """
    return RECORD_LIMIT - RECORD_OVERHEAD


def output_record_bytes(max_chars: int) -> int:
    """What one of these records needs, in the bytes the seam counts — a ceiling
    that **cannot** be exceeded, because :func:`captured_output` clips to it.

    Two bounds meet, and the smaller wins: what ``max_chars`` could cost in the
    worst encoding, and what the budget allows at all.
    """
    return RECORD_OVERHEAD + min(
        2 + WORST_BYTES_PER_CHAR * max(0, max_chars), output_budget())


def captured_output(stdout: str, stderr: str, *, capture: str,
                    max_chars: int, keep: str) -> str:
    """The captured output as it will be both kept and shown: the configured
    stream, stripped, and clipped once — ``max_chars`` characters off the
    configured end, then into the byte budget from that same end."""
    if capture == "stdout":
        text = stdout
    elif capture == "stderr":
        text = stderr
    else:
        text = (stdout or "") + (stderr or "")
    return clip(text.strip(), chars=max_chars, budget=output_budget(),
                keep=keep)


def failure_text(text: str) -> str:
    """A run that produced no exit code, said in the record: clipped like
    everything else that enters one, so the declaration above stays a ceiling."""
    return clip(text, chars=FAILURE_CHARS, budget=FAILURE_BYTES)


def output_reading(record: Mapping[str, Any]) -> tuple[int | None, str, str]:
    """A record of this shape, read back: ``(exit_code, output, failure)``.

    One reader for three checks, so that what a grading may assume about one of
    these records is written down once."""
    exit_code = record.get("exit_code")
    return (int(exit_code) if isinstance(exit_code, (int, float)) else None,
            str(record.get("output") or ""),
            str(record.get("error") or ""))

