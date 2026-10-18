"""Stable, width-priced track allocation for the status dashboard.

The browser knows one fact only it can know — how wide the responsive grid
currently is.  The server knows the shape rendered at the selected depth.  The
server prices that shape at every grid width that could change the answer and
publishes a deterministic span plan per width band; the browser merely selects
the band its measured width falls in.  Status, live reason text and chip/box
painting never participate, so polling cannot make a root jump between columns.

Widths are modeled **and published** in integer tenths of a pixel; the client
compares them against ``width * 10``, so no band is late against a browser's
fractional width.  The layout constants mirror ``static/css/overview.css`` and
are pinned to it by a structural test, so the stylesheet cannot drift away from
the model silently.

The shape priced is the page's **first look** (ADR-0128 decision 6), as the
configuration draws it and never as a status or a click does: an open node is
the box it always was, a closed one a chip in its level's run, each run as many
heading rows as it has lines of chips at the level's width, and a closed
top-level card one row (:class:`Priced`).  Nothing beneath a chip is priced.
A run in a level narrower than two of its columns and their gap wraps as it
comes (backlog #91's note, §2, 2026-10-17), each chip at its own width — the
model's column the server's estimate, where the stylesheet's is the column the
browser draws.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from little_sister.config import DEFAULT_REASON_CAP
from little_sister.tree import StatusSnapshot

MAX_LAYOUT_TRACKS = 32

# Integer tenths of a pixel, mirroring overview.css: a 330px ordinary track, a
# 1rem outer gap, the card's horizontal padding, a .4rem nested gap, and a
# nested box's padding plus border.  The model is deliberately discrete: it
# needs to know at which widths another 330px nested column can exist, not
# predict rendered text height.
_TRACK_WIDTH = 3300
_OUTER_GAP = 160
_CARD_INSET = 200
_NESTED_GAP = 64
_NODE_INSET = 180
# CSS grid resolves fractional pixels while this model uses integer tenths,
# and the width division floors at tenth precision.  One tenth of a pixel
# absorbs exactly that rounding; anything larger skews the model's nested
# column flips a visible pixel away from the browser's (found live: at a full
# pixel of tolerance the model promoted a nested column at ~1338px where
# Chromium held until ~1340px, so event-driven tests probed the wrong width).
_COLUMN_TOLERANCE = 1

# The widest grid the model prices; a still wider browser reuses the last plan
# and leaves the additional room empty, exactly like the CSS fallback would.
_MAX_GRID_WIDTH = (MAX_LAYOUT_TRACKS * _TRACK_WIDTH
                   + (MAX_LAYOUT_TRACKS - 1) * _OUTER_GAP)
# The widest track auto-fill itself can ever resolve: one track just before a
# second fits.  An explicitly chosen count may never stretch a track past
# this, so the flow only uses track widths the responsive design already
# exhibits somewhere — the rule that forbids page-wide banner stacking without
# banning the moderate counts a re-chunking dodge needs.
_MAX_CHOSEN_TRACK = 2 * _TRACK_WIDTH + _OUTER_GAP
# No card content can be wider than the full grid; content-width thresholds
# beyond this can never be reached and are dropped early.
_MAX_CONTENT_WIDTH = _MAX_GRID_WIDTH

# A run of chips (ADR-0127 decision 12): the column gap between its chips,
# 0.3rem, as overview.css's aligned runs have it; and a chip as the server
# estimates it before the script measures it (backlog #91's note, §2, 2026-10-17),
# which the model needs only to tell how many chips share a line, and below two
# columns where the run wraps as it comes. Each character of its name and its
# count is ``CHIP_LETTER`` of a ``0`` of the chip's font — a font's measure and no
# stylesheet's, a ``0`` of about 0.55em of the chip's 0.8rem in the system faces
# the page names, ``_CHIP_CH`` — and its chrome is the stylesheet's: its padding
# and border, ``CHIP_EDGE_PX``, its cue and the cue's margin, ``CHIP_CUE_EM``, and
# where its level counts the counts' margin, ``CHIP_COUNTS_EM``, in ems of that
# font, ``_CHIP_EM``. A theme drawn in a face of its own says how wide its
# characters stand (:data:`CHIP_FACES`, 2026-10-18). A level whose estimate is
# missing takes the stylesheet's fallback, ``12ch``.
_CHIP_GAP = 48
_CHIP_CH = 70
_CHIP_EM = 128
CHIP_LETTER = 0.85
CHIP_EDGE_PX = 20
CHIP_CUE_EM = 1.15
CHIP_COUNTS_EM = 0.5
_CHIP_FALLBACK = 12 * _CHIP_CH


@dataclass(frozen=True)
class ChipFace:
    """How wide a chip's characters stand in a theme's face, as the estimate counts
    them: each at ``letter`` of a ``0`` of the chip's font — the stylesheet's
    ``--ls-chip-letter`` in that theme, which the estimate's length reads — and the
    ``0`` itself ``zero`` tenths of a pixel at the chip's 0.8rem, the font's own
    measure."""

    letter: float
    zero: int


#: The system's proportional faces, every theme's but those named below: a name's
#: letters run at 0.6 to 0.9 of a ``0``, and a ``0`` is about 0.55em.
CHIP_FACE = ChipFace(CHIP_LETTER, _CHIP_CH)
#: The themes drawn in a face of their own (backlog #91's note, §2, 2026-10-18):
#: cyberpunk's monospace one, where every character is a whole ``0`` of 0.6em.
CHIP_FACES: Mapping[str, ChipFace] = {"cyberpunk": ChipFace(1.0, 77)}


def chip_face(theme: str) -> ChipFace:
    """The face the chips of ``theme`` are drawn in: its own, or the system's."""
    return CHIP_FACES.get(theme, CHIP_FACE)


def _chip_ems(counts: bool) -> float:
    return CHIP_CUE_EM + (CHIP_COUNTS_EM if counts else 0.0)


def chip_width(chars: int, counts: bool, face: ChipFace = CHIP_FACE) -> int:
    """A chip's width as the server estimates it, in the model's tenths of a pixel:
    ``chars`` characters of its name and its count at the ``face``'s letter of its
    ``0``, and its chrome — its padding and border, its cue, and where ``counts`` the
    counts' margin."""
    return round(chars * face.letter * face.zero + CHIP_EDGE_PX * 10
                 + _chip_ems(counts) * _CHIP_EM)


def chip_estimate(chars: int, counts: bool) -> str:
    """The same estimate as a length of the stylesheet's, a level's ``--chip-w``
    before the script measures it, which the run's font — the chip's — resolves:
    each character at the theme's ``--ls-chip-letter`` of a ``ch``."""
    return (f"calc({chars} * var(--ls-chip-letter) * 1ch + {CHIP_EDGE_PX}px"
            f" + {_chip_ems(counts):g}em)")


@dataclass(frozen=True)
class Priced:
    """What the planner prices of a page's first look beside its shape (ADR-0128
    decision 6), none of it read off a status: the nodes the configuration closes
    — a ``depth=`` level among them — each node's line budget where it has its
    own, by a level's node the server's estimate of its chips' column width,
    ``--chip-w`` (ADR-0127 decision 12), and by a closed node its chip at its own
    width, which a run that holds one column wraps by — both in tenths of a pixel
    (:func:`chip_width`), a chip not named there as wide as its level's column. A
    closed top-level card is one row and a closed node beneath it a chip in its
    level's run; what the failure budget opens and what ✓ folds are never priced,
    so no status moves a card."""

    closed: frozenset[str] = frozenset()
    caps: Mapping[str, int] = field(default_factory=dict)
    chip_w: Mapping[str, int] = field(default_factory=dict)
    chip_own: Mapping[str, int] = field(default_factory=dict)


#: A node as the model reads it: its stable cost, its level's chip column width
#: in tenths where a run stands among its children (else ``0``), its children's
#: shapes in their declared order, ``None`` for a closed one — a chip, beneath
#: which nothing is priced — and those chips' own widths in tenths, in the same
#: order.
_Shape = tuple[int, int, tuple["_Shape | None", ...], tuple[int, ...]]


@dataclass(frozen=True)
class FlowStep:
    """One card span that materially shortens its stable flow height."""

    span: int
    height: int


FlowProfile = tuple[FlowStep, ...]


@dataclass(frozen=True)
class DashboardLayout:
    """Stable flow data, diagnostic plans and width breakpoints for one grid.

    ``plans[0]`` is the one-track plan at the 330px minimum and so on — kept
    for Python tests and diagnostics.  The template sends only
    ``breakpoints``: ``(tenths, tracks, plan)`` entries where ``tenths`` is
    the smallest grid width **in integer tenths of a pixel** at which the band
    applies — the model's own unit, so a band is never late against a
    browser's fractional width — strictly rising, each band differing from
    its predecessor.  ``tracks`` is the outer track count the plan was built
    for — the client sets the grid to exactly that many equal tracks, which is
    what lets a plan keep four wide tracks at a width where ``auto-fill``
    would snap to five minimum ones.  A
    ``tracks`` of ``0`` means "let auto-fill decide", emitted only for an
    all-ones plan, which is valid at every track count — so a flat grid still
    ships one band.  A grid narrower than the first entry keeps the CSS
    auto-fill fallback.
    """

    weights: tuple[int, ...]
    profiles: tuple[FlowProfile, ...]
    plans: tuple[tuple[int, ...], ...]
    breakpoints: tuple[tuple[int, int, tuple[int, ...]], ...]


def _reason_cost(reason_cap: int) -> int:
    """Stable per-node cost implied by the configured line budget."""
    if reason_cap < 0:
        raise ValueError("reason_cap must not be negative")
    # Every node owns a heading row, even when reasons are disabled.
    return max(1, (reason_cap + DEFAULT_REASON_CAP - 1) // DEFAULT_REASON_CAP)


def visible_node_count(node: StatusSnapshot, remaining_depth: int) -> int:
    """Count rendered nodes rooted at ``node`` at the selected depth.

    Every one of them is also a potential reason host: branches as well as
    leaves can own a reason block, which is why the flow model prices each
    visible node by the configured reason budget.  This is topology rather
    than content — a poll may replace every reason and the answer stands.
    """
    if remaining_depth <= 0:
        return 1
    return 1 + sum(
        visible_node_count(child, remaining_depth - 1)
        for child in node.children
    )


def _shape(node: StatusSnapshot, remaining_depth: int, reason_cost: int,
           priced: Priced | None = None) -> _Shape:
    """The depth-limited shape of ``node``'s subtree as the model prices it.

    Its cost scales only with the line budget — the node's own, where the first
    look gives it one, else ``reason_cost`` — and never with its current lines.
    A child the first look closes is a chip, its subtree unpriced; the chips'
    column width is the level's estimate from the names of all its children,
    which reads no status either.
    """
    cost = reason_cost
    if priced is not None and node.path in priced.caps:
        cost = _reason_cost(priced.caps[node.path])
    if remaining_depth <= 0 or not node.children:
        return (cost, 0, (), ())
    closed = priced.closed if priced is not None else frozenset()
    kids = tuple(
        None if child.path in closed
        else _shape(child, remaining_depth - 1, reason_cost, priced)
        for child in node.children
    )
    chip_w = 0
    own: tuple[int, ...] = ()
    if None in kids:
        chip_w = (priced.chip_w.get(node.path, _CHIP_FALLBACK)
                  if priced is not None else _CHIP_FALLBACK)
        owns = priced.chip_own if priced is not None else {}
        own = tuple(owns.get(child.path, chip_w)
                    for child, kid in zip(node.children, kids, strict=True)
                    if kid is None)
    return (cost, chip_w, kids, own)


def _nested_columns(width: int, child_count: int, runs: bool = False) -> int:
    """The tracks a level's open boxes stand in at ``width``.

    Two or more open boxes make the level a grid of auto-fit 330px tracks, which
    drops its empty tracks — unless a run of chips spans the row: a run spans
    every track, so none is empty, and the boxes keep the width of all the tracks
    that fit, however few of them they fill (measured in Chromium: two boxes
    beside a run at 1,400 pixels each take a quarter of the level).
    """
    if child_count < 2:
        return 1
    fitting = (
        (width + _NESTED_GAP + _COLUMN_TOLERANCE)
        // (_TRACK_WIDTH + _NESTED_GAP)
    )
    return max(1, fitting) if runs else min(child_count, max(1, fitting))


def _run_lines(chips: Sequence[int], chip_w: int, width: int) -> int:
    """The lines a run takes at a level ``width`` wide, ``chips`` its chips' own
    widths: as many to a line as columns of ``chip_w`` fit, from two on; below
    two, the run wraps as it comes (backlog #91's note, §2, 2026-10-17) — each chip
    at its own width with the gap after it, a line holding what fits and a chip
    wider than the level a line of its own."""
    per_line = (width + _CHIP_GAP) // (chip_w + _CHIP_GAP)
    if per_line >= 2:
        return -(-len(chips) // per_line)
    lines = 0
    used = width
    for own in chips:
        needs = own + _CHIP_GAP
        if used + needs > width:
            lines += 1
            used = needs
        else:
            used += needs
    return lines


def _level_rows(kids: Sequence[_Shape | None], heights: Iterator[int],
                columns: int, chip_w: int, width: int,
                own: Sequence[int] = ()) -> int:
    """The rows a level costs: its open boxes, ``heights`` in their order,
    chunked into rows of ``columns`` between its runs — a row as tall as its
    tallest box — and each run its lines of chips, where it stands, ``own`` its
    chips' own widths in order (each as wide as the column where it is short)."""
    rows = 0
    boxes: list[int] = []
    chips: list[int] = []
    widths = iter(own)

    def boxes_rows() -> int:
        return sum(max(boxes[start:start + columns])
                   for start in range(0, len(boxes), columns))

    for kid in kids:
        if kid is None:
            if boxes:
                rows += boxes_rows()
                boxes = []
            chips.append(next(widths, chip_w))
            continue
        if chips:
            rows += _run_lines(chips, chip_w, width)
            chips = []
        boxes.append(next(heights))
    if chips:
        rows += _run_lines(chips, chip_w, width)
    if boxes:
        rows += boxes_rows()
    return rows


def _shape_height(shape: _Shape | None, width: int) -> int:
    """Stable vertical flow rows for one shape at ``width``: the straight-line
    reference evaluation, re-walking the subtree at every width."""
    if shape is None:
        return 1
    cost, chip_w, kids, own = shape
    if not kids:
        return cost
    boxes = [kid for kid in kids if kid is not None]
    columns = _nested_columns(width, len(boxes), len(boxes) < len(kids))
    child_width = max(
        1,
        (width - _NESTED_GAP * (columns - 1)) // columns - _NODE_INSET,
    )
    heights = iter([_shape_height(box, child_width) for box in boxes])
    return cost + _level_rows(kids, heights, columns, chip_w, width, own)


def _flow_height(node: StatusSnapshot, remaining_depth: int, width: int,
                 reason_cost: int, priced: Priced | None = None) -> int:
    """Estimate stable vertical flow rows for ``node`` at ``width``.

    Every visible node owns a heading and can own a reason block, so its stable
    cost scales only with the configured reason-line cap; it never inspects
    current reason count or text.  Siblings share rows once the CSS can fit
    another ordinary nested column, and a row costs its tallest branch; a run of
    chips costs its lines.
    """
    return _shape_height(_shape(node, remaining_depth, reason_cost, priced), width)


def _shape_pieces(shape: _Shape | None) -> tuple[tuple[int, int], ...]:
    """A shape's modeled height as ``(from_width, height)`` pieces.

    Built bottom-up: each node combines its **children's pieces** instead of
    re-walking its whole subtree at every threshold, so a node's work is
    proportional to its own children and their piece counts.  (The first
    version evaluated ``_flow_height`` over the complete subtree at every
    propagated threshold, which measured 0.4s at a thousand leaves and 6.7s
    at ten thousand — a per-poll price for merely deep deployments.)

    A node's height can change where its own nested column count flips —
    ``k`` ordinary tracks first fit, every count that can while a run holds the
    level's tracks — where a run's chips per line change, below two columns where
    a stretch of a run's chips first fits on one line, and where a child's
    height changes, mapped back through the exact integer arithmetic the width
    division uses.  The union is a superset of the true change points, which is
    all correctness needs: a spurious threshold merges away as an equal piece.
    ``_shape_height`` remains the straight-line reference implementation; a
    differential test holds the two together.
    """
    if shape is None:
        return ((1, 1),)
    cost, chip_w, kids, own = shape
    if not kids:
        return ((1, cost),)

    boxes = [kid for kid in kids if kid is not None]
    runs = len(boxes) < len(kids)
    child_pieces = [_shape_pieces(box) for box in boxes]
    child_bounds = sorted({
        bound
        for pieces in child_pieces
        for bound, _height in pieces[1:]
    })

    thresholds: set[int] = {1}
    most = (0 if len(boxes) < 2
            else MAX_LAYOUT_TRACKS if runs
            else min(len(boxes), MAX_LAYOUT_TRACKS))
    for columns in range(1, max(1, most) + 1):
        if columns >= 2:
            flip = (columns * (_TRACK_WIDTH + _NESTED_GAP)
                    - _NESTED_GAP - _COLUMN_TOLERANCE)
            if flip <= _MAX_CONTENT_WIDTH:
                thresholds.add(flip)
        gap_total = _NESTED_GAP * (columns - 1)
        for bound in child_bounds:
            mapped = columns * (bound + _NODE_INSET) + gap_total
            if 1 < mapped <= _MAX_CONTENT_WIDTH:
                thresholds.add(mapped)
    chip_runs: list[list[int]] = []
    widths = iter(own)
    chips: list[int] = []
    for kid in kids:
        if kid is None:
            chips.append(next(widths, chip_w))
        elif chips:
            chip_runs.append(chips)
            chips = []
    if chips:
        chip_runs.append(chips)
    longest = max((len(run) for run in chip_runs), default=0)
    for per_line in range(2, longest + 1):
        reach = per_line * (chip_w + _CHIP_GAP) - _CHIP_GAP
        if 1 < reach <= _MAX_CONTENT_WIDTH:
            thresholds.add(reach)
    # below two columns a run wraps as it comes: its lines change where a stretch
    # of its chips, each with the gap after it, first fits on one
    bound = 2 * chip_w + _CHIP_GAP
    for run in chip_runs:
        for start, first in enumerate(run):
            reach = first + _CHIP_GAP
            for own_width in run[start + 1:]:
                reach += own_width + _CHIP_GAP
                if reach >= bound:
                    break
                if 1 < reach <= _MAX_CONTENT_WIDTH:
                    thresholds.add(reach)

    pieces: list[tuple[int, int]] = []
    for width in sorted(thresholds):
        columns = _nested_columns(width, len(boxes), runs)
        child_width = max(
            1,
            (width - _NESTED_GAP * (columns - 1)) // columns - _NODE_INSET,
        )
        heights = iter([_piece_height(child, child_width)
                        for child in child_pieces])
        height = cost + _level_rows(kids, heights, columns, chip_w, width, own)
        if not pieces or pieces[-1][1] != height:
            pieces.append((width, height))
    return tuple(pieces)


def _height_pieces(node: StatusSnapshot, remaining_depth: int,
                   reason_cost: int,
                   priced: Priced | None = None) -> tuple[tuple[int, int], ...]:
    """The subtree's modeled height as ``(from_width, height)`` pieces
    (:func:`_shape_pieces`), the node itself never closed: a closed top-level
    card is priced by :func:`dashboard_layout`."""
    return _shape_pieces(_shape(node, remaining_depth, reason_cost, priced))


def _piece_height(pieces: Sequence[tuple[int, int]], width: int) -> int:
    """The modeled height at ``width``, by binary search over the pieces."""
    index = bisect_right(pieces, max(1, width), key=lambda piece: piece[0])
    return pieces[max(0, index - 1)][1]


def _track_count(grid_width: int) -> int:
    """Ordinary 330px tracks the auto-fill grid resolves at ``grid_width``."""
    fitting = (grid_width + _OUTER_GAP) // (_TRACK_WIDTH + _OUTER_GAP)
    return max(1, min(MAX_LAYOUT_TRACKS, fitting))


def _grid_start(tracks: int) -> int:
    """The smallest grid width resolving ``tracks`` ordinary tracks."""
    if tracks <= 1:
        return 1
    return tracks * _TRACK_WIDTH + (tracks - 1) * _OUTER_GAP


def _span_width(grid_width: int, tracks: int, span: int) -> int:
    """Content width of a card spanning ``span`` of ``tracks`` at this grid.

    The browser distributes a real viewport's leftover across its tracks, so
    a resolved track is at least 330px and usually wider; this prices the card
    at the width it actually has rather than at the global minimum — the
    correction this module exists for.
    """
    lanes = span * (grid_width - (tracks - 1) * _OUTER_GAP) // tracks
    return max(1, lanes + (span - 1) * _OUTER_GAP - _CARD_INSET)


def _profile_at(pieces: Sequence[tuple[int, int]], grid_width: int,
                tracks: int) -> FlowProfile:
    """Useful span steps for one root at one concrete grid width.

    A candidate span enters only when, since the preceding useful span, it
    removes at least one stable flow row per additional outer track.  A span
    too narrow to open the next nested column therefore never appears, and a
    linear chain has no wider step at all.
    """
    steps = [FlowStep(1, _piece_height(pieces, _span_width(grid_width,
                                                           tracks, 1)))]
    if len(pieces) > 1:
        for span in range(2, tracks + 1):
            height = _piece_height(pieces, _span_width(grid_width, tracks,
                                                       span))
            previous = steps[-1]
            if previous.height - height >= span - previous.span:
                steps.append(FlowStep(span, height))
    return tuple(steps)


def flow_profile(node: StatusSnapshot, remaining_depth: int, reason_cap: int,
                 max_span: int = MAX_LAYOUT_TRACKS,
                 priced: Priced | None = None) -> FlowProfile:
    """The useful span steps at the 330px track minimum, for diagnostics.

    The published breakpoints price each width band exactly; this fixed-width
    profile remains the readable summary the harness sheet and the card's
    ``data-layout-steps`` attribute carry.
    """
    if max_span < 1:
        raise ValueError("max_span must be at least 1")
    pieces = _height_pieces(node, remaining_depth, _reason_cost(reason_cap),
                            priced)
    return _profile_at(pieces, _grid_start(max_span), max_span)


def _validate_profile(profile: FlowProfile) -> None:
    if not profile or profile[0].span != 1 or profile[0].height < 1:
        raise ValueError("profiles must start with a positive one-track step")
    for previous, step in pairwise(profile):
        if step.span <= previous.span or step.height >= previous.height:
            raise ValueError("profile spans must rise while heights fall")


def allocate_spans(profiles: Sequence[FlowProfile],
                   track_count: int) -> tuple[int, ...]:
    """Allocate useful span steps within each consecutive source-order row.

    Every card starts at one track.  A candidate step may consume several spare
    tracks at once; that is essential when span two buys nothing but span three
    opens a nested column.  A grid row is as tall as its **tallest** card, so
    among cards whose next step fits the remaining tracks the currently tallest
    one wins — the min-max objective; equal heights fall back to the greater
    stable-height reduction per added track, and exact ties stay with the
    earlier card.  (A pure gain-per-track rule measurably misallocates: two
    equal thirty-node roots on a fourteen-track grid gave one root twelve
    tracks and the other two, because every one of the twelve paid a row —
    while the row's height was owned by the starved neighbor the whole time.)
    Unusable spare tracks remain empty rather than padding a card with width
    its descendants cannot exploit.
    """
    if track_count < 1:
        raise ValueError("track_count must be at least 1")
    for profile in profiles:
        _validate_profile(profile)

    spans = [1] * len(profiles)
    positions = [0] * len(profiles)
    for start in range(0, len(profiles), track_count):
        stop = min(start + track_count, len(profiles))
        spare = track_count - (stop - start)
        while spare:
            winner = -1
            winner_height = 0
            winner_gain = 0
            winner_cost = 1
            for index in range(start, stop):
                profile = profiles[index]
                position = positions[index]
                if position + 1 >= len(profile):
                    continue
                current = profile[position]
                candidate = profile[position + 1]
                cost = candidate.span - current.span
                if cost > spare or candidate.span > track_count:
                    continue
                gain = current.height - candidate.height
                # Tallest current card first; then the better reduction per
                # track, cross-multiplied rather than floated.  Both strict,
                # so exact ties keep the deterministic source order.
                if (winner < 0 or current.height > winner_height
                        or (current.height == winner_height
                            and gain * winner_cost > winner_gain * cost)):
                    winner = index
                    winner_height = current.height
                    winner_gain = gain
                    winner_cost = cost
            if winner < 0:
                break
            positions[winner] += 1
            spans[winner] = profiles[winner][positions[winner]].span
            spare -= winner_cost
    return tuple(spans)


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _track_floor(grid_width: int) -> int:
    """The fewest tracks a plan may choose at ``grid_width``.

    A chosen track may never be wider than auto-fill itself can resolve (one
    track just before a second fits), so the flow only ever uses track widths
    the responsive design already exhibits somewhere.  Exposed because the
    tests assert "never worse than the best **legal** choice" and must read
    the planner's own rule rather than restate it.
    """
    return max(1, _ceil_div(grid_width + _OUTER_GAP,
                            _MAX_CHOSEN_TRACK + _OUTER_GAP))


def _allocation_at(pieces_per_root: Sequence[Sequence[tuple[int, int]]],
                   grid_width: int,
                   tracks: int) -> tuple[int, int, tuple[int, ...]]:
    """The plan for ``tracks`` equal tracks at ``grid_width``, with its cost.

    The primary cost is the **modeled page height**: consecutive source-order
    rows of up to ``tracks`` cards, each row as tall as its tallest allocated
    card — the number a viewer's scrollbar answers to.  The secondary cost is
    the **sum of the allocated heights**: two candidates can hide the same
    tallest card while one of them leaves a second tower standing beside it,
    and the row maximum alone cannot see that difference.
    """
    profiles = [
        _profile_at(pieces, grid_width, tracks)
        for pieces in pieces_per_root
    ]
    spans = allocate_spans(profiles, tracks)
    page, total = _plan_cost(pieces_per_root, grid_width, tracks, spans)
    return page, total, spans


def _plan_cost(pieces_per_root: Sequence[Sequence[tuple[int, int]]],
               grid_width: int, tracks: int,
               spans: Sequence[int]) -> tuple[int, int]:
    """Reprice a **fixed** plan at ``grid_width``: (page, summed heights).

    Used to keep an incumbent band honest as the grid widens: its spans and
    track count stay what they were, its cards only get wider — but a wider
    card is **not** always a shorter one, because its nested auto-fit can
    re-chunk source-ordered children into worse rows at a column flip.  The
    repricing is what surfaces exactly that, so the sweep can switch to a
    challenger where one exists — and where none does, the rise is the
    card's own and no outer track choice could have prevented it.
    """
    heights = [
        _piece_height(pieces, _span_width(grid_width, tracks, span))
        for pieces, span in zip(pieces_per_root, spans, strict=True)
    ]
    page = sum(
        max(heights[start:start + tracks])
        for start in range(0, len(heights), tracks)
    )
    return page, sum(heights)


def _band_events(
        pieces_per_root: Sequence[Sequence[tuple[int, int]]],
) -> dict[int, set[int]]:
    """Grid widths (tenths) mapped to the track counts whose pricing changes.

    For a fixed track count a card's content width rises linearly with the
    grid, so each root height piece maps to the smallest grid width where a
    given span reaches it.  Spurious events are harmless — the affected count
    is repriced and equal bands collapse — so the set is a superset, never a
    guess.  Once available, a track count stays priced for every wider grid;
    its plan only changes at its own events.
    """
    events: dict[int, set[int]] = {}
    for tracks in range(1, MAX_LAYOUT_TRACKS + 1):
        start = _grid_start(tracks)
        events.setdefault(start, set()).add(tracks)
        gap_total = (tracks - 1) * _OUTER_GAP
        for pieces in pieces_per_root:
            if len(pieces) < 2:
                continue
            for span in range(1, tracks + 1):
                span_gaps = (span - 1) * _OUTER_GAP - _CARD_INSET
                for bound, _height in pieces[1:]:
                    # Smallest W with _span_width(W, tracks, span) >= bound.
                    lanes = bound - span_gaps
                    width = _ceil_div(tracks * lanes, span) + gap_total
                    if start < width <= _MAX_GRID_WIDTH:
                        events.setdefault(width, set()).add(tracks)
    return events


def _plan_breakpoints(
        pieces_per_root: Sequence[Sequence[tuple[int, int]]],
) -> tuple[tuple[int, int, tuple[int, ...]], ...]:
    """``(tenths, tracks, plan)`` bands over the grid width, changes only.

    At every event width the affected track counts are repriced and the band
    is the candidate with the smallest modeled page height — ties fall to the
    smallest summed card height (two candidates can hide the same tallest
    card while one leaves a second tower standing beside it), then to more
    tracks, so an indifferent grid behaves exactly like ``auto-fill``.  A
    track count never leaves the candidate set once its width is reached, so
    the published band is never worse than the best legal outer choice at its
    width: where ``auto-fill`` snaps every track back to the 330px minimum,
    the previous count is still on offer and still priced at its now wider
    tracks.  (Never worse *than the alternatives* — not never taller.  A
    card's own nested auto-fit can re-chunk at a column flip with no outer
    choice able to prevent it; that limit is ADR-0056's, recorded there.)

    A candidate may not stretch a track wider than auto-fill itself ever
    could (one track just before a second fits, ~676px) — equivalently the
    count may not drop below about half the auto-fill count.  That forbids
    the page-wide banner stacking one enormous card would win as the
    modeled-shortest page, while keeping the moderate counts a dodge needs:
    the first floor, ``min(roots, auto-fill count)``, grew with the viewport
    and disqualified exactly the counts that were holding the page — twelve
    linear roots of mixed heights rose 15 → 16 modeled rows when the eighth
    track re-chunked them and the seven-track hold was below the floor, and
    a randomized wall rose 47 → 48 the same way.

    An all-ones plan chosen at the auto-fill count is published with a track
    count of ``0`` ("let auto-fill decide"): it is valid at every count, and
    it keeps a flat eighty-root grid at one band instead of one per count.

    Widths are computed **and published in integer tenths of a pixel**, the
    model's own unit, and the client compares them against ``width * 10``.
    Publishing the ceiling in whole pixels instead used to leave a band up to
    0.9px late — nine times the column tolerance — and a browser reports
    fractional widths, so at 1037.5px a wall could carry a 105-row plan while
    a legal candidate offered 75 until the next whole pixel.
    """
    events = _band_events(pieces_per_root)
    priced: dict[int, tuple[int, int, tuple[int, ...]]] = {}
    breakpoints: list[tuple[int, int, tuple[int, ...]]] = []
    incumbent: tuple[int, tuple[int, ...]] | None = None
    for grid_width in sorted(events):
        for tracks in events[grid_width]:
            priced[tracks] = _allocation_at(pieces_per_root, grid_width,
                                            tracks)
        autofill = _track_count(grid_width)
        floor = _track_floor(grid_width)
        held_tracks = (incumbent[0] or autofill) if incumbent else 0
        # The floor constrains *new* track counts, never the held one: the
        # incumbent's count is already on the wall, and re-spanning at that
        # same count is exactly the move that dodges a nested column flip
        # inside an unchanged band.  (Nine roots, the ninth ending in two
        # deep chains: at the width where its nested grid went five columns
        # to six, the chains landed in separate rows and the fixed plan rose
        # 12 -> 17 modeled rows — while the then-current floor, grown past
        # the incumbent's own count, banned the same-count re-allocation
        # that keeps the card at five columns.)
        page, total, negated, plan = min(
            (page, total, -tracks, plan)
            for tracks, (page, total, plan) in priced.items()
            if tracks >= floor or tracks == held_tracks
        )
        challenger = (-negated, plan)
        if incumbent is not None:
            # The incumbent never expires: its tracks still fit and only got
            # wider.  A greedy reallocation at the same count can genuinely
            # come out worse, so the challenger must strictly beat the
            # incumbent as repriced at *this* width — that inequality is what
            # keeps the published band at the best legal outer choice, and it
            # is why a snap cannot cost the wall a plan it already had.
            held = _plan_cost(pieces_per_root, grid_width, held_tracks,
                              incumbent[1])
            if (page, total, negated) >= (*held, -held_tracks):
                continue
        tracks = challenger[0]
        if tracks == autofill and set(plan) <= {1}:
            tracks = 0
        band = (tracks, plan)
        if band == incumbent:
            continue
        # Events are distinct widths in tenths, so a band start is unique and
        # needs no collision handling: publish the exact width that earns it.
        breakpoints.append((grid_width, *band))
        incumbent = band
    return tuple(breakpoints)


# Every number in a DashboardLayout is a pure function of the depth-limited
# tree *shape* — each node's stable cost, which children the first look closes
# and each level's chip width — so names, statuses and reasons never enter, and
# one memo entry serves every poll until the topology, the view depth or what
# the configuration says actually changes.  A handful of entries covers the
# depth control's values; the cap only guards against a pathological churn of
# node sets.  Entries are immutable, so the worst a concurrent render can do is
# compute one twice.
_MEMO_CAP = 16
_memo: dict[tuple[_Shape | None, ...], DashboardLayout] = {}


def dashboard_layout(nodes: Sequence[StatusSnapshot], max_depth: int,
                     reason_cap: int = DEFAULT_REASON_CAP,
                     priced: Priced | None = None) -> DashboardLayout:
    """Build stable flow pieces, diagnostic plans and width breakpoints for the
    page's top-level cards, ``nodes``, as its first look draws them (``priced``,
    every node open where it is ``None``)."""
    remaining_depth = max(0, max_depth - 1)
    cost = _reason_cost(reason_cap)
    closed = priced.closed if priced is not None else frozenset()
    key = tuple(
        None if node.path in closed
        else _shape(node, remaining_depth, cost, priced)
        for node in nodes
    )
    cached = _memo.get(key)
    if cached is not None:
        return cached
    pieces_per_root = tuple(_shape_pieces(shape) for shape in key)
    weights = tuple(
        _piece_height(pieces, _span_width(_TRACK_WIDTH, 1, 1))
        for pieces in pieces_per_root
    )
    profiles = tuple(
        _profile_at(pieces, _grid_start(MAX_LAYOUT_TRACKS),
                    MAX_LAYOUT_TRACKS)
        for pieces in pieces_per_root
    )
    plans = tuple(
        allocate_spans(
            tuple(_profile_at(pieces, _grid_start(track_count), track_count)
                  for pieces in pieces_per_root),
            track_count,
        )
        for track_count in range(1, MAX_LAYOUT_TRACKS + 1)
    )
    layout = DashboardLayout(
        weights=weights,
        profiles=profiles,
        plans=plans,
        breakpoints=_plan_breakpoints(pieces_per_root),
    )
    if len(_memo) >= _MEMO_CAP:
        _memo.pop(next(iter(_memo)))
    _memo[key] = layout
    return layout
