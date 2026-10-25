/* Stable-flow dashboard card spans (ADR-0056).
 *
 * The server owns product semantics: each card carries stable flow diagnostics
 * and the grid carries width breakpoints — `[tenths, tracks, plan]` bands, the
 * smallest grid width in **tenths of a pixel** at which each deterministic plan
 * applies.  Tenths are the model's own unit and a browser reports a fractional
 * width, so the comparison below scales the measurement rather than rounding the
 * threshold: rounding up to whole pixels used to leave a band up to 0.9px late,
 * and a wall could carry a plan far worse than an available one across that gap.
 * The browser owns the one fact only it knows: how wide the responsive grid
 * currently is.  A band names the outer track count its plan was priced for,
 * and this script sets the grid to exactly that many equal tracks — that is
 * what stops CSS auto-fill from snapping every track back to the 330px minimum
 * the moment one more fits, which used to make a one-pixel-wider viewport paint
 * a dramatically taller page.  A track count of 0 means "let auto-fill decide"
 * (only ever sent with an all-ones plan, which is valid at any count).
 * Selecting a band never inspects card height, status, live reasons or chip/box
 * painting, so a status-only poll cannot move a root.
 *
 * The persistent #status-grid container is observed rather than the replaceable
 * .status-grid element.  That makes one binding cover the initial page, the ~10s
 * poll's innerHTML swap, viewport changes and rail expansion.  If data is absent
 * or malformed, inline spans and columns are cleared and CSS's ordinary
 * auto-fill grid wins.
 *
 * `tree.js` reads the cards' head rows, which need the widths the plan gives, so
 * it has the plan laid at once (`window.lsLayout.apply()`) before it reads them;
 * the frame after a swap then finds the plan in place and writes nothing.
 */
(function () {
    "use strict";

    var root = document.getElementById("status-grid");
    if (!root) { return; }

    var queued = false;
    var observedWidth = null;

    function cardsOf(grid) {
        var cards = [];
        for (var i = 0; i < grid.children.length; i++) {
            if (grid.children[i].classList.contains("status-card")) {
                cards.push(grid.children[i]);
            }
        }
        return cards;
    }

    function clear(grid, cards) {
        grid.style.gridTemplateColumns = "";
        grid.removeAttribute("data-layout-tracks");
        for (var i = 0; i < cards.length; i++) {
            cards[i].style.gridColumn = "";
            cards[i].removeAttribute("data-layout-span");
        }
    }

    function trackCount(grid) {
        // Inline columns have already been cleared, so the computed explicit
        // grid is CSS's auto-fill fallback. Browsers resolve repeat()/minmax()
        // to one whitespace-separated used value per track. Used only as the
        // safety clamp when a band leaves the count to auto-fill — selection
        // and explicit counts go by measured width.
        var columns = getComputedStyle(grid).gridTemplateColumns.trim();
        if (!columns || columns === "none") { return 1; }
        return columns.split(/\s+/).length;
    }

    // Whether the grid carries the plan its width selects already — what the frame
    // after a swap finds once `tree.js` has had the grid planned: then nothing is
    // written, and that frame lays nothing out again. A band that leaves the count to
    // auto-fill carries only ones, which every count holds.
    function carries(grid, cards, tracks, plan) {
        if (grid.getAttribute("data-layout-tracks")
                !== (tracks > 0 ? String(tracks) : null)) {
            return false;
        }
        for (var i = 0; i < cards.length; i++) {
            var span = Number(plan[i]);
            if ((tracks === 0 && span !== 1)
                    || cards[i].getAttribute("data-layout-span") !== String(span)) {
                return false;
            }
        }
        return true;
    }

    function layout() {
        var grid = root.querySelector(".status-grid");
        if (!grid) { return; }
        var cards = cardsOf(grid);
        if (!cards.length) {
            clear(grid, cards);
            return;
        }

        var breakpoints;
        try {
            breakpoints = JSON.parse(
                grid.getAttribute("data-layout-breakpoints") || ""
            );
        } catch (error) {
            clear(grid, cards);
            return;
        }
        if (!Array.isArray(breakpoints) || !breakpoints.length) {
            clear(grid, cards);
            return;
        }

        // The grid's own width is its container's, whatever its columns and spans,
        // so it is read as the grid stands: after a swap `tree.js` has had planned,
        // in the layout the frame needs anyway rather than in one of a cleared grid.
        var width = grid.getBoundingClientRect().width * 10;
        var tracks = 0;
        var plan = null;
        var previousWidth = 0;
        for (var point = 0; point < breakpoints.length; point++) {
            var entry = breakpoints[point];
            if (!Array.isArray(entry) || entry.length !== 3) {
                clear(grid, cards);
                return;
            }
            var entryWidth = Number(entry[0]);
            var entryTracks = Number(entry[1]);
            if (!Number.isInteger(entryWidth) || entryWidth < 1
                    || (point > 0 && entryWidth <= previousWidth)
                    || !Number.isInteger(entryTracks) || entryTracks < 0) {
                clear(grid, cards);
                return;
            }
            previousWidth = entryWidth;
            if (entryWidth > width) { break; }
            tracks = entryTracks;
            plan = entry[2];
        }
        if (!Array.isArray(plan) || plan.length !== cards.length) {
            clear(grid, cards);
            return;
        }
        if (carries(grid, cards, tracks, plan)) { return; }
        clear(grid, cards);
        if (tracks > 0) {
            grid.style.gridTemplateColumns =
                "repeat(" + tracks + ", minmax(0, 1fr))";
            grid.setAttribute("data-layout-tracks", String(tracks));
        } else {
            tracks = Math.max(1, trackCount(grid));
        }
        for (var i = 0; i < cards.length; i++) {
            var span = Number(plan[i]);
            if (!Number.isInteger(span) || span < 1 || span > tracks) {
                clear(grid, cards);
                return;
            }
            cards[i].style.gridColumn = "span " + span;
            cards[i].setAttribute("data-layout-span", String(span));
        }
    }

    // --- the look `boxes: packed` (ADR-0138) ---------------------------------------
    //
    // Under it every grid of open boxes — the cards of a wall or of a node's page, and
    // a level of two or more open boxes inside a card — stands its boxes in columns
    // rather than in rows: each box goes beneath the shortest column, or the shortest
    // run of columns it spans, so that a tall box leaves no gap beside it. The grid
    // stays the grid the plan lays and the stylesheet draws, its columns and each
    // card's span with them, and every box stands in its first row, in its column,
    // with a top margin as deep as the boxes above it in that column and the level's
    // gap beneath each of them: the row is as tall as the tallest column, to the
    // pixel, and the level as tall as its boxes make it. A run of chips stands in one
    // column as a box does, its chips wrapping to the column's width, and a level of
    // a card lays its columns itself, as many as fit and its boxes and runs fill: a
    // column a click empties stays where it stood, where the stylesheet's would give
    // its width to the others. A card's own levels are packed before the card is,
    // since they make its height. A packed level carries `.is-packed`.
    //
    // A box takes its column when the page is drawn and when its level's columns
    // change, which a width does, and keeps it otherwise: a refresh, a click or a box's
    // lines growing restack the columns and move no box sideways. A node keeps its
    // column as a box and as a chip — a card a click closes leaves its chip where its
    // box stood, a chip a click opens stands its box where the chip stood, and a run
    // stands where the first of its nodes that stood anywhere did — and a box new to
    // its level takes the shortest column at its turn. The page is drawn once
    // `tree.js` has put the tab's map back (`draw`), and until then the stylesheet
    // hides the wall, so that its first paint never stands the boxes in rows for the
    // packing to move. The keyboard's order is the page's, which the packing leaves
    // alone.

    // The row every packed box stands in, as the browser writes it back.
    var PACK_ROW = "1";
    // A column within this of the shortest is as short, and the leftmost of them is
    // taken, so that boxes of about one height keep their reading order: a line of a
    // box's lines, some 26 pixels, and a little.
    var PACK_TOLERANCE = 32;
    // What each level's boxes stand in, held while the page is open: its columns, and
    // by a node's path the first column and span it stands in — a box's own, a chip's
    // its run's.
    var packs = new Map();
    var watcher = null;
    var watched = [];
    var watching = new WeakSet();

    function packing() {
        return document.body.getAttribute("data-ls-boxes") === "packed";
    }

    function isGrid(el) {
        return getComputedStyle(el).display === "grid";
    }

    function depthOf(el) {
        var depth = 0;
        for (var up = el; up; up = up.parentElement) { depth++; }
        return depth;
    }

    // The columns a level stands its boxes in: an auto-fit level draws the tracks it
    // leaves empty nought wide.
    function columnsOf(level) {
        var tracks = getComputedStyle(level).gridTemplateColumns.trim().split(/\s+/);
        var count = 0;
        for (var i = 0; i < tracks.length; i++) {
            if (parseFloat(tracks[i]) > 0) { count++; }
        }
        return count;
    }

    // The grid's items: its children, and the child of a wrapper drawn without a box
    // of its own (`.tree-solo`, `display: contents`).
    function boxesOf(level) {
        var boxes = [];
        for (var i = 0; i < level.children.length; i++) {
            var child = level.children[i];
            var display = getComputedStyle(child).display;
            if (display === "none") { continue; }
            if (display === "contents") {
                for (var j = 0; j < child.children.length; j++) {
                    boxes.push(child.children[j]);
                }
                continue;
            }
            boxes.push(child);
        }
        return boxes;
    }

    function levelKey(level) {
        if (level.classList.contains("status-grid")) { return "grid"; }
        var node = level.closest("[data-node]");
        return node ? "level " + node.getAttribute("data-node") : null;
    }

    function isRun(box) {
        return box.classList.contains("tree-run");
    }

    function spanOf(box, columns) {
        if (isRun(box)) { return 1; }
        var span = Number(box.getAttribute("data-layout-span")) || 1;
        return Math.max(1, Math.min(columns, span));
    }

    // The nodes a grid item holds its column by: a box's own, or each of a run's.
    function namesOf(box) {
        var nodes = isRun(box) ? box.children : [box];
        var names = [];
        for (var i = 0; i < nodes.length; i++) {
            var name = nodes[i].getAttribute("data-node");
            if (name !== null) { names.push(name); }
        }
        return names;
    }

    // A node a click closed stood as a box, and the place the packing gave it goes
    // with it into its run, where the margin above it would stand its chip as low as
    // its box stood: the run's nodes are given none.
    function settle(run) {
        for (var i = 0; i < run.children.length; i++) {
            var style = run.children[i].style;
            if (style.gridColumn) { style.gridColumn = ""; }
            if (style.gridRow) { style.gridRow = ""; }
            if (style.marginTop) { style.marginTop = ""; }
        }
    }

    function topOf(fill, start, span) {
        var top = 0;
        for (var c = start; c < start + span; c++) { top = Math.max(top, fill[c]); }
        return top;
    }

    // The first column of the shortest run of `span` columns: an empty run before any
    // other, then the leftmost within the tolerance of the shortest.
    function shortest(fill, used, span) {
        var columns = fill.length;
        var start;
        for (start = 0; start + span <= columns; start++) {
            var empty = true;
            for (var c = start; c < start + span; c++) { if (used[c]) { empty = false; } }
            if (empty) { return start; }
        }
        var low = Infinity;
        for (start = 0; start + span <= columns; start++) {
            low = Math.min(low, topOf(fill, start, span));
        }
        for (start = 0; start + span <= columns; start++) {
            if (topOf(fill, start, span) <= low + PACK_TOLERANCE) { return start; }
        }
        return 0;
    }

    // The level as its own grid lays it: a box the packing placed in a column past
    // the grid's own would stand the grid that column too, and it would be read.
    function unplace(level, boxes) {
        if (!level.classList.contains("is-packed")) { return; }
        level.classList.remove("is-packed");
        if (!level.classList.contains("status-grid")) {
            level.style.gridTemplateColumns = "";
        }
        for (var i = 0; i < boxes.length; i++) {
            var span = boxes[i].getAttribute("data-layout-span");
            boxes[i].style.gridColumn = span ? "span " + span : "";
            boxes[i].style.gridRow = "";
            boxes[i].style.marginTop = "";
            if (isRun(boxes[i])) { settle(boxes[i]); }
        }
    }

    function packLevel(level) {
        var boxes = boxesOf(level);
        var key = levelKey(level);
        var width = Math.round(level.getBoundingClientRect().width);
        var held = packs.get(key);
        // a level of a card; the page's grid is the plan's to lay
        var own = !level.classList.contains("status-grid");
        var columns;
        var i;
        if (held && Math.abs(held.width - width) <= 1) {
            columns = held.columns;
        } else {
            unplace(level, boxes);
            columns = columnsOf(level);
            // the stylesheet stands a run across every track that fits; packed it
            // stands in one, so the level has as many as its boxes and runs fill
            if (own) { columns = Math.min(columns, boxes.length); }
        }
        if (columns < 2 || boxes.length < 2 || key === null) {
            unplace(level, boxes);
            packs.delete(key);
            return;
        }
        level.classList.add("is-packed");
        var tracks = "repeat(" + columns + ", minmax(0, 1fr))";
        if (own && level.style.gridTemplateColumns !== tracks) {
            level.style.gridTemplateColumns = tracks;
        }
        // a run is read one column wide, as it will stand: one new to the level would
        // stand across it the stylesheet's way until it is placed
        for (i = 0; i < boxes.length; i++) {
            if (!isRun(boxes[i])) { continue; }
            settle(boxes[i]);
            if (!boxes[i].style.gridColumn) { boxes[i].style.gridColumn = "span 1"; }
        }
        // every box read in one layout, then every one placed: its height with the
        // margin beneath it, since the margin above it is where the packing stands it
        var heights = [];
        var spans = [];
        for (i = 0; i < boxes.length; i++) {
            heights.push(boxes[i].getBoundingClientRect().height
                         + (parseFloat(getComputedStyle(boxes[i]).marginBottom) || 0));
            spans.push(spanOf(boxes[i], columns));
        }
        // a level whose columns, or a box's span, are not what they were — a width
        // brought them — is packed afresh; one wider or narrower with the columns it
        // had, as a scrollbar makes it, keeps every box in its column. A node that
        // stood as a chip spanned one column, as every box of a card's level does, so
        // a click that opens it never packs its level afresh
        var fresh = !held || held.columns !== columns;
        for (i = 0; !fresh && i < boxes.length; i++) {
            if (isRun(boxes[i])) { continue; }
            var was = held.at.get(boxes[i].getAttribute("data-node"));
            if (was && was.span !== spans[i]) { fresh = true; }
        }
        if (fresh) {
            held = { columns: columns, width: width, at: new Map() };
            packs.set(key, held);
        }
        held.width = width;
        var gap = parseFloat(getComputedStyle(level).columnGap) || 0;
        // where each column's last box ends, in pixels from the level's top
        var fill = [];
        var used = [];
        for (i = 0; i < columns; i++) { fill.push(0); used.push(false); }
        var seen = new Set();
        for (i = 0; i < boxes.length; i++) {
            var box = boxes[i];
            var span = spans[i];
            var names = namesOf(box);
            // where it stood: a box where its node did, as a box or as a chip, and a
            // run where the first of its nodes that stood anywhere did
            var start = -1;
            var n;
            for (n = 0; start < 0 && n < names.length; n++) {
                var stood = held.at.get(names[n]);
                if (stood) { start = stood.start; }
            }
            if (start < 0 || start + span > columns) {
                start = shortest(fill, used, span);
            }
            for (n = 0; n < names.length; n++) {
                held.at.set(names[n], { start: start, span: span });
                seen.add(names[n]);
            }
            var top = topOf(fill, start, span);
            for (var c = start; c < start + span; c++) {
                if (used[c]) { top += gap; break; }
            }
            var column = (start + 1) + " / span " + span;
            var margin = Math.round(top * 100) / 100 + "px";
            if (box.style.gridColumn !== column) { box.style.gridColumn = column; }
            if (box.style.gridRow !== PACK_ROW) { box.style.gridRow = PACK_ROW; }
            if (box.style.marginTop !== margin) { box.style.marginTop = margin; }
            for (c = start; c < start + span; c++) {
                fill[c] = top + heights[i];
                used[c] = true;
            }
        }
        held.at.forEach(function (_where, name) {
            if (!seen.has(name)) { held.at.delete(name); }
        });
        watch(boxes);
    }

    // A box's lines grow and shrink with a refresh, a click or *⌄ all N*: the columns
    // restack before the frame is painted, so no box ever stands over another. Its
    // border box is watched, which is what the packing measures.
    function watch(boxes) {
        if (!window.ResizeObserver) { return; }
        if (!watcher) { watcher = new ResizeObserver(restack); }
        watched = watched.filter(function (box) {
            if (box.isConnected) { return true; }
            watcher.unobserve(box);
            watching.delete(box);
            return false;
        });
        for (var i = 0; i < boxes.length; i++) {
            if (!watching.has(boxes[i])) {
                watching.add(boxes[i]);
                watched.push(boxes[i]);
                watcher.observe(boxes[i], { box: "border-box" });
            }
        }
    }

    function pack() {
        if (!packing()) { return; }
        var levels = [];
        var all = root.querySelectorAll(".status-grid, .status-card .node-children");
        for (var i = 0; i < all.length; i++) {
            if (isGrid(all[i])) {
                levels.push(all[i]);
            } else if (all[i].classList.contains("is-packed")) {
                // a level a click left one open box is no grid, and stands its boxes
                // as rows do, with no margin the packing gave them
                unplace(all[i], boxesOf(all[i]));
                packs.delete(levelKey(all[i]));
            }
        }
        levels.sort(function (a, b) { return depthOf(b) - depthOf(a); });
        for (i = 0; i < levels.length; i++) { packLevel(levels[i]); }
    }

    // The page drawn — loaded, reloaded or reached, once `tree.js` has put the tab's
    // map back: every box takes its column anew, by the heights it is drawn with,
    // whatever a frame before the map packed it by.
    function draw() {
        packs.clear();
        pack();
    }

    function scheduled() {
        queued = false;
        layout();
        pack();
    }

    // A box changed size, or a width changed every box's: the plan the width selects
    // is laid first, since a level's columns are what it lays, and then the boxes are
    // packed, before the frame is painted.
    function restack() {
        layout();
        pack();
    }

    function schedule() {
        if (queued) { return; }
        queued = true;
        window.requestAnimationFrame(scheduled);
    }

    // `tree.js` reads each card's rows at the width the card's span gives it, so it
    // has the grid planned at once before it reads them — after a swap, before the
    // frame this script would plan it in; and under `boxes: packed` it has the boxes
    // packed once it has drawn them, before it puts the window back where it stood:
    // anew on a load, and in their columns after a refresh or a click.
    window.lsLayout = { apply: layout, pack: pack, draw: draw };

    new MutationObserver(schedule).observe(root, {childList: true, subtree: true});
    new ResizeObserver(function (entries) {
        var width = entries.length ? entries[0].contentRect.width : root.clientWidth;
        if (width !== observedWidth) {
            observedWidth = width;
            schedule();
        }
    }).observe(root);
    schedule();
}());
